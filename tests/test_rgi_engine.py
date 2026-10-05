"""Tests del RGI Engine.

Los dobles del catálogo son deterministas y viven aquí: el motor no toca la
base, así que estos casos son reproducibles y no dependen de que Persona 2
tenga la tarifa cargada.

Lo que más se prueba es lo que el motor debe NEGARSE a hacer. Un clasificador
que siempre devuelve un código es fácil de escribir y peligroso de usar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from core.rgi_engine import (
    ClassificationContext,
    ProductFact,
    RGIStatus,
    TariffCandidate,
    classify,
)
from core.rgi_engine.rules import RGI2, RGI3B, RGI5

pytestmark = pytest.mark.unit

OPERACION = date(2024, 3, 15)


# ── Dobles ───────────────────────────────────────────────────────────────────


class CatalogoFalso:
    """Catálogo en memoria. Implementa el puerto `TariffCatalog`."""

    def __init__(
        self,
        headings: list[TariffCandidate] | None = None,
        subheadings: list[TariffCandidate] | None = None,
        fractions: list[TariffCandidate] | None = None,
    ) -> None:
        self._headings = headings or []
        self._subheadings = subheadings or []
        self._fractions = fractions or []
        self.fechas_consultadas: list[date] = []

    def headings(self, *, on_date: date, terms: list[str]) -> list[TariffCandidate]:  # type: ignore[override]
        self.fechas_consultadas.append(on_date)
        return list(self._headings)

    def subheadings(self, *, on_date: date, heading: str) -> list[TariffCandidate]:  # type: ignore[override]
        self.fechas_consultadas.append(on_date)
        return [s for s in self._subheadings if s.code.startswith(heading)]

    def fractions(self, *, on_date: date, subheading: str) -> list[TariffCandidate]:  # type: ignore[override]
        self.fechas_consultadas.append(on_date)
        return [f for f in self._fractions if f.code.startswith(subheading)]


class NotasFalsas:
    """Notas legales en memoria. Implementa el puerto `LegalNotes`."""

    def __init__(self, exclusiones: dict[str, str] | None = None) -> None:
        self._exclusiones = exclusiones or {}

    def notes_for(self, *, on_date: date, chapter: str) -> list[str]:  # type: ignore[override]
        return []

    def excludes(self, *, on_date: date, heading: str, terms: list[str]) -> str | None:  # type: ignore[override]
        return self._exclusiones.get(heading)


class InterpreteFalso:
    """Intérprete controlado, para probar la RGI 3 b) sin llamar a un modelo."""

    def __init__(
        self, terms: list[str] | None = None, essential: tuple[str, str] | None = None
    ) -> None:
        self._terms = terms or []
        self._essential = essential

    def suggest_terms(self, *, context: ClassificationContext) -> list[str]:  # type: ignore[override]
        return list(self._terms)

    def essential_character(
        self, *, context: ClassificationContext, candidates: list
    ) -> tuple[str, str] | None:  # type: ignore[override]
        return self._essential


def contexto(**cambios: object) -> ClassificationContext:
    base: dict[str, object] = {
        "description": "Computadora portátil de 16 pulgadas",
        "operation_date": OPERACION,
        "facts": (
            ProductFact(name="function", value="tratamiento de datos", status="OBSERVED"),
            ProductFact(name="weight", value="1.4 kg", status="EXTRACTED"),
        ),
        "search_terms": ("máquina automática para tratamiento de datos",),
    }
    base.update(cambios)
    return ClassificationContext(**base)  # type: ignore[arg-type]


PARTIDA_8471 = TariffCandidate(
    code="8471",
    text="Máquinas automáticas para tratamiento o procesamiento de datos",
    level="HEADING",
    source_id="src-ligie-84",
    specificity=8,
)
SUB_847130 = TariffCandidate(
    code="847130",
    text="Portátiles, de peso inferior o igual a 10 kg",
    level="SUBHEADING",
    source_id="src-ligie-8471",
    specificity=5,
)
FRAC_84713001 = TariffCandidate(
    code="84713001",
    text="Unidades de proceso digitales portátiles",
    level="FRACTION",
    source_id="src-ligie-847130",
    specificity=5,
)


def catalogo_completo() -> CatalogoFalso:
    return CatalogoFalso([PARTIDA_8471], [SUB_847130], [FRAC_84713001])


# ── El camino que resuelve ───────────────────────────────────────────────────


def test_una_sola_partida_resuelve_por_rgi1_y_baja_por_rgi6() -> None:
    """El caso limpio: RGI 1 fija la partida, RGI 6 desciende a la fracción."""
    traza = classify(contexto(), catalog=catalogo_completo(), notes=NotasFalsas())

    assert traza.final_status is RGIStatus.RESOLVED
    assert traza.resolved_code == "84713001"
    assert traza.applied_rule == "RGI-6"
    assert [p.rule_id for p in traza.steps] == ["RGI-1", "RGI-6"]
    assert traza.requires_human_review is False


def test_la_traza_conserva_el_razonamiento_de_cada_paso() -> None:
    """Sin razonamiento no hay nada que defender ante una auditoría (§18)."""
    traza = classify(contexto(), catalog=catalogo_completo(), notes=NotasFalsas())

    assert all(p.reasoning_summary for p in traza.steps)
    assert "8471" in traza.steps[0].reasoning_summary
    assert "84713001" in traza.steps[-1].reasoning_summary


def test_toda_consulta_al_catalogo_lleva_la_fecha_de_la_operacion() -> None:
    """§14: no se clasifica una operación de 2024 con la tarifa de 2026."""
    cat = catalogo_completo()
    classify(contexto(), catalog=cat, notes=NotasFalsas())

    assert cat.fechas_consultadas
    assert all(f == OPERACION for f in cat.fechas_consultadas)


def test_las_fuentes_se_arrastran_para_poder_citarlas() -> None:
    """Sin source_ids no se puede responder "¿con qué fuente?" del §49."""
    traza = classify(contexto(), catalog=catalogo_completo(), notes=NotasFalsas())

    todas = {s for p in traza.steps for s in p.source_ids}
    assert "src-ligie-84" in todas


# ── Lo que el motor debe NEGARSE a hacer ─────────────────────────────────────


def test_sin_terminos_de_busqueda_no_inventa_nada() -> None:
    """Sin con qué buscar, se declara insuficiente en vez de adivinar (§8.2)."""
    traza = classify(contexto(search_terms=()), catalog=catalogo_completo(), notes=NotasFalsas())

    assert traza.final_status is RGIStatus.INSUFFICIENT_INFORMATION
    assert traza.resolved_code is None
    assert "search_terms" in traza.missing_information


def test_sin_partida_que_comprenda_la_mercancia_no_hay_clasificacion() -> None:
    """Cero coincidencias es INSUFFICIENT_INFORMATION, no una fracción cualquiera."""
    traza = classify(contexto(), catalog=CatalogoFalso([]), notes=NotasFalsas())

    assert traza.final_status is RGIStatus.INSUFFICIENT_INFORMATION
    assert traza.resolved_code is None


def test_lo_que_falta_es_accionable() -> None:
    """`missing_information` se le pide al importador: deben ser nombres de datos."""
    traza = classify(
        contexto(
            search_terms=(),
            facts=(
                ProductFact(name="voltage", status="MISSING"),
                ProductFact(name="materials", status="MISSING"),
            ),
        ),
        catalog=catalogo_completo(),
        notes=NotasFalsas(),
    )

    assert "voltage" in traza.missing_information
    assert "materials" in traza.missing_information


def test_una_nota_de_exclusion_descarta_la_partida_aunque_el_texto_encaje() -> None:
    """Las notas pesan más que el texto de la partida: es lo que dice la RGI 1."""
    traza = classify(
        contexto(),
        catalog=catalogo_completo(),
        notes=NotasFalsas({"8471": "Este capítulo no comprende las máquinas de la partida 84.70."}),
    )

    assert traza.final_status is RGIStatus.INSUFFICIENT_INFORMATION
    assert "excluida por nota" in traza.steps[0].reasoning_summary


def test_varias_fracciones_aplicables_no_se_deciden_al_azar() -> None:
    """Elegir mal la fracción cambia el arancel que paga el importador."""
    cat = CatalogoFalso(
        [PARTIDA_8471],
        [SUB_847130],
        [
            FRAC_84713001,
            TariffCandidate(code="84713002", text="Las demás", level="FRACTION", specificity=5),
        ],
    )
    traza = classify(contexto(), catalog=cat, notes=NotasFalsas())

    assert traza.final_status is RGIStatus.HUMAN_REVIEW_REQUIRED
    assert traza.resolved_code is None
    assert traza.requires_human_review


# ── La partida se elige por lo que dice el texto (RGI 1 y 3a) ────────────────
#
# Caso real del corpus: una tubería de acero al carbono de ⌀ 508 mm terminaba
# clasificada en la partida 8481 —artículos de grifería— porque las cuatro
# candidatas empataban en `specificity` y la RGI 3 c) elegía la última por
# orden de numeración.

PARTIDAS_TUBERIA = [
    TariffCandidate(
        code="3926",
        text="Las demás manufacturas de plástico y manufacturas de las demás materias.",
        level="HEADING",
        specificity=2,
    ),
    TariffCandidate(
        code="7305",
        text=(
            "Los demás tubos de sección circular con diámetro exterior superior a 406.4 mm, "
            "de hierro o acero."
        ),
        level="HEADING",
        specificity=2,
    ),
    TariffCandidate(
        code="7306", text="Los demás tubos y perfiles huecos.", level="HEADING", specificity=2
    ),
    TariffCandidate(
        code="8481",
        text="Artículos de grifería y órganos similares para tuberías, calderas o depósitos.",
        level="HEADING",
        specificity=2,
    ),
]


def _contexto_tuberia(**cambios: object) -> ClassificationContext:
    base: dict[str, object] = {
        "description": "TUBERIA DE ACERO AL CARBONO SOLDADA, DIAMETRO EXTERIOR 508 MM",
        "operation_date": OPERACION,
        "facts": (
            ProductFact(name="material", value="acero al carbono", status="OBSERVED"),
            ProductFact(name="diametro_exterior_mm", value="508", status="OBSERVED"),
        ),
        "search_terms": ("tubos de acero",),
    }
    base.update(cambios)
    return ClassificationContext(**base)  # type: ignore[arg-type]


def test_una_tuberia_de_acero_no_acaba_en_griferia() -> None:
    """EL TEST QUE IMPORTA.

    Antes: las cuatro candidatas empataban en `specificity`, la RGI 3 a) no
    distinguía y la RGI 3 c) elegía «la última por orden de numeración» — 8481,
    artículos de grifería, para un tubo de acero. Y luego se atascaba bajando
    por una partida que nunca debería haber elegido.

    Ahora gana 7305, que fija un umbral medible —⌀ superior a 406.4 mm— que la
    mercancía cumple con 508.
    """
    cat = CatalogoFalso(PARTIDAS_TUBERIA, [], [])
    traza = classify(_contexto_tuberia(), catalog=cat, notes=NotasFalsas())

    paso_3a = next(p for p in traza.steps if p.rule_id == "RGI-3a")
    assert paso_3a.status is RGIStatus.RESOLVED
    assert [c.code for c in paso_3a.candidate_codes] == ["7305"]
    assert "condición medible" in paso_3a.reasoning_summary


def test_el_acero_descarta_la_partida_de_plastico() -> None:
    """Una mercancía que consta de acero no puede ser «manufactura de plástico».

    Se descarta en la RGI 1, igual que una nota de exclusión, y se dice por qué.
    """
    cat = CatalogoFalso(PARTIDAS_TUBERIA, [], [])
    traza = classify(_contexto_tuberia(), catalog=cat, notes=NotasFalsas())

    paso_1 = traza.steps[0]
    assert "3926" not in [c.code for c in paso_1.candidate_codes]
    assert "3926 descartada" in paso_1.reasoning_summary
    assert "plastico" in paso_1.reasoning_summary


def test_una_partida_que_nombra_las_dos_materias_no_se_descarta() -> None:
    """«De plástico reforzado con acero» no contradice a una mercancía de acero.

    Descartarla sería quitar la partida correcta por nombrar otra materia de
    paso.
    """
    cat = CatalogoFalso(
        [
            TariffCandidate(
                code="3926",
                text="Manufacturas de plástico reforzado con acero.",
                level="HEADING",
                specificity=2,
            ),
        ],
        [],
        [],
    )
    traza = classify(_contexto_tuberia(), catalog=cat, notes=NotasFalsas())

    assert "3926" in [c.code for c in traza.steps[0].candidate_codes]


def test_sin_material_en_la_ficha_no_se_descarta_por_materia() -> None:
    """La descripción comercial no sirve para esto.

    Un cable de acero con alma de fibra nombra dos materias en su descripción;
    adivinar cuál manda descartaría la partida correcta. Sólo cuenta un hecho
    sólido cuyo nombre hable de materia.
    """
    cat = CatalogoFalso(PARTIDAS_TUBERIA, [], [])
    sin_material = _contexto_tuberia(
        facts=(ProductFact(name="diametro_exterior_mm", value="508", status="OBSERVED"),)
    )
    traza = classify(sin_material, catalog=cat, notes=NotasFalsas())

    assert "3926" in [c.code for c in traza.steps[0].candidate_codes]


def test_una_condicion_que_la_mercancia_incumple_no_la_hace_ganar() -> None:
    """Cumplir es lo que vale; tener una condición, no.

    Con ⌀ 200 la tubería NO supera los 406.4 mm, así que 7305 no gana por ahí y
    el motor vuelve al camino de siempre.
    """
    cat = CatalogoFalso(PARTIDAS_TUBERIA, [], [])
    estrecha = _contexto_tuberia(
        facts=(
            ProductFact(name="material", value="acero al carbono", status="OBSERVED"),
            ProductFact(name="diametro_exterior_mm", value="200", status="OBSERVED"),
        )
    )
    traza = classify(estrecha, catalog=cat, notes=NotasFalsas())

    paso_3a = next(p for p in traza.steps if p.rule_id == "RGI-3a")
    assert paso_3a.status is RGIStatus.CONTINUE


def test_sin_el_dato_la_condicion_no_cuenta_ni_a_favor_ni_en_contra() -> None:
    """El silencio de la ficha no cumple ni incumple.

    Sin diámetro, 7305 no gana por su umbral, y el motor no lo inventa.
    """
    cat = CatalogoFalso(PARTIDAS_TUBERIA, [], [])
    mudo = _contexto_tuberia(
        facts=(ProductFact(name="material", value="acero al carbono", status="OBSERVED"),)
    )
    traza = classify(mudo, catalog=cat, notes=NotasFalsas())

    paso_3a = next(p for p in traza.steps if p.rule_id == "RGI-3a")
    assert paso_3a.status is RGIStatus.CONTINUE


# ── Descarte por contradicción (RGI 6) ───────────────────────────────────────
#
# El caso es real: el cable de acero galvanizado 6x19 de ⌀10 mm del corpus, y
# las cinco fracciones de 7312.10 tal como están en la TIGIE.

PARTIDA_7312 = TariffCandidate(
    code="7312",
    text="Cables, trenzas, eslingas y artículos similares, de hierro o acero",
    level="HEADING",
    source_id="src-ligie-73",
    specificity=8,
)
SUB_731210 = TariffCandidate(
    code="731210", text="Cables.", level="SUBHEADING", source_id="src-ligie-7312", specificity=1
)
FRAC_CABLE = [
    TariffCandidate(
        code="73121001",
        text="Galvanizados, con diámetro mayor de 4 mm, constituidos por más de 5 alambres.",
        level="FRACTION",
        specificity=1,
    ),
    TariffCandidate(
        code="73121005",
        text="De acero sin recubrimiento, con o sin lubricación.",
        level="FRACTION",
        specificity=1,
    ),
    TariffCandidate(
        code="73121007",
        text=(
            "Galvanizados, con un diámetro mayor a 4 mm pero inferior a 19 mm, "
            "constituidos por 7 alambres."
        ),
        level="FRACTION",
        specificity=3,
    ),
    TariffCandidate(
        code="73121008",
        text="Sin galvanizar, de diámetro menor o igual a 19 mm, constituidos por 7 alambres.",
        level="FRACTION",
        specificity=3,
    ),
    TariffCandidate(code="73121099", text="Los demás.", level="FRACTION", specificity=0),
]


def _contexto_cable(**cambios: object) -> ClassificationContext:
    base: dict[str, object] = {
        "description": "CABLE DE ACERO GALVANIZADO, CONSTRUCCION 6X19, DIAMETRO 10 MM",
        "operation_date": OPERACION,
        "facts": (
            ProductFact(name="material", value="acero galvanizado", status="OBSERVED"),
            ProductFact(name="construccion", value="6x19", status="OBSERVED"),
            ProductFact(name="diametro_mm", value="10", status="OBSERVED"),
        ),
        "search_terms": ("cables de acero",),
    }
    base.update(cambios)
    return ClassificationContext(**base)  # type: ignore[arg-type]


def test_descartar_no_convierte_una_negativa_honesta_en_una_fraccion_equivocada() -> None:
    """EL TEST QUE IMPORTA.

    Es la razón de que el descarte sólo resuelva cuando queda UNA. El diseño
    obvio —quitar la contradicha y desempatar entre las supervivientes por
    `specificity`— daría `73121007` para este cable: su texto exige «7
    alambres» y una construcción 6x19 son 114. El motor hoy empata y se niega,
    que es la respuesta correcta.

    Una mejora que convierte una negativa honesta en una fracción equivocada
    no es una mejora: es un arancel mal pagado con apariencia de rigor.
    """
    cat = CatalogoFalso([PARTIDA_7312], [SUB_731210], FRAC_CABLE)
    traza = classify(_contexto_cable(), catalog=cat, notes=NotasFalsas())

    assert traza.final_status is RGIStatus.HUMAN_REVIEW_REQUIRED
    assert traza.resolved_code is None
    assert traza.requires_human_review


def test_la_contradiccion_se_descarta_y_se_dice_por_que() -> None:
    """«Sin galvanizar» no puede ser un cable que consta galvanizado.

    Aunque no resuelva, el descarte es trabajo útil: el clasificador recibe
    cuatro candidatas en vez de cinco, y con el motivo escrito.
    """
    cat = CatalogoFalso([PARTIDA_7312], [SUB_731210], FRAC_CABLE)
    traza = classify(_contexto_cable(), catalog=cat, notes=NotasFalsas())

    paso = traza.steps[-1]
    assert "73121008" in paso.reasoning_summary
    assert "galvanizar" in paso.reasoning_summary
    # Y ya no se le ofrece como candidata viva.
    assert "73121008" not in [c.code for c in paso.candidate_codes]


def test_si_la_contradiccion_deja_una_sola_el_motor_si_resuelve() -> None:
    """Cuando descartar deja exactamente una, hay un motivo para elegirla.

    No es «la más específica»: es «la única que la mercancía no contradice»,
    que es una afirmación que un agente aduanal puede firmar.
    """
    cat = CatalogoFalso(
        [PARTIDA_7312],
        [SUB_731210],
        [
            TariffCandidate(
                code="73121001",
                text="Galvanizados, con diámetro mayor de 4 mm.",
                level="FRACTION",
                specificity=1,
            ),
            TariffCandidate(
                code="73121008",
                text="Sin galvanizar, de diámetro menor o igual a 19 mm.",
                level="FRACTION",
                specificity=3,
            ),
        ],
    )
    traza = classify(_contexto_cable(), catalog=cat, notes=NotasFalsas())

    assert traza.final_status is RGIStatus.RESOLVED
    assert traza.resolved_code == "73121001"
    assert "no contradice" in traza.steps[-1].reasoning_summary


def test_con_o_sin_no_es_una_negacion() -> None:
    """«con o sin lubricación» PERMITE las dos cosas.

    Leerlo como negación descartaría la fracción correcta de una mercancía
    lubricada. El paréntesis negativo del patrón existe por esto.
    """
    cat = CatalogoFalso(
        [PARTIDA_7312],
        [SUB_731210],
        [
            TariffCandidate(
                code="73121005",
                text="De acero, con o sin lubricación.",
                level="FRACTION",
                specificity=1,
            ),
        ],
    )
    contexto_lubricado = _contexto_cable(
        facts=(ProductFact(name="acabado", value="lubricado", status="OBSERVED"),)
    )
    traza = classify(contexto_lubricado, catalog=cat, notes=NotasFalsas())

    assert traza.resolved_code == "73121005"


def test_el_silencio_de_la_ficha_no_es_una_negacion() -> None:
    """Que la mercancía no mencione una característica no significa que no la
    tenga. Tratar el silencio como negación descartaría la correcta.

    Aquí la ficha no dice nada de galvanizado, así que «Sin galvanizar» sigue
    siendo posible y no se descarta.
    """
    cat = CatalogoFalso([PARTIDA_7312], [SUB_731210], FRAC_CABLE)
    mudo = _contexto_cable(
        description="CABLE DE ACERO, CONSTRUCCION 6X19",
        facts=(ProductFact(name="construccion", value="6x19", status="OBSERVED"),),
    )
    traza = classify(mudo, catalog=cat, notes=NotasFalsas())

    assert traza.final_status is RGIStatus.HUMAN_REVIEW_REQUIRED
    assert "73121008" in [c.code for c in traza.steps[-1].candidate_codes]


def test_un_codigo_inventado_por_el_modelo_se_rechaza() -> None:
    """La máquina existe justamente para atrapar esto (§36).

    Un modelo puede devolver una partida que suena bien y no está en la tarifa.
    Si el motor la aceptara, todo lo demás —evidencia, vigencia, auditoría—
    estaría construido sobre un código inventado.
    """
    a = TariffCandidate(code="8471", text="Máquinas automáticas", level="HEADING", specificity=3)
    b = TariffCandidate(code="8528", text="Monitores", level="HEADING", specificity=3)

    resultado = RGI3B().evaluate(
        contexto(),
        candidates=[a, b],
        catalog=CatalogoFalso(),
        notes=NotasFalsas(),
        interpreter=InterpreteFalso(essential=("9999", "me lo inventé")),
    )

    assert resultado.status is RGIStatus.HUMAN_REVIEW_REQUIRED
    assert "no está entre los candidatos" in resultado.reasoning_summary


# ── Reglas no implementadas: escalan, no se saltan ───────────────────────────


def test_rgi2_detecta_articulo_sin_montar_y_escala() -> None:
    """Una regla no implementada que devolviera CONTINUE clasificaría mal."""
    resultado = RGI2().evaluate(
        contexto(description="Bicicleta desmontada para ensamblar, en kit"),
        candidates=[PARTIDA_8471],
        catalog=CatalogoFalso(),
        notes=NotasFalsas(),
    )

    assert resultado.status is RGIStatus.HUMAN_REVIEW_REQUIRED
    assert "RGI 2" in resultado.reasoning_summary


def test_rgi2_no_estorba_cuando_no_aplica() -> None:
    """Escalar de más también es un defecto: saturaría la revisión humana."""
    resultado = RGI2().evaluate(
        contexto(),
        candidates=[PARTIDA_8471],
        catalog=CatalogoFalso(),
        notes=NotasFalsas(),
    )

    assert resultado.status is RGIStatus.CONTINUE


def test_rgi5_detecta_estuche_y_escala() -> None:
    """Un estuche que sigue la suerte del contenido cambia la clasificación."""
    resultado = RGI5().evaluate(
        contexto(description="Juego de herramientas en estuche de plástico"),
        candidates=[PARTIDA_8471],
        catalog=CatalogoFalso(),
        notes=NotasFalsas(),
    )

    assert resultado.status is RGIStatus.HUMAN_REVIEW_REQUIRED


def test_dos_partidas_sin_desempate_terminan_en_rgi3c_con_confianza_baja() -> None:
    """La RGI 3 c) resuelve, pero llegar ahí significa que nada la distinguió."""
    a = TariffCandidate(code="8471", text="Máquinas automáticas", level="HEADING", specificity=3)
    b = TariffCandidate(code="8528", text="Monitores", level="HEADING", specificity=3)
    cat = CatalogoFalso([a, b], [SUB_847130], [FRAC_84713001])

    traza = classify(contexto(), catalog=cat, notes=NotasFalsas())

    aplicadas = [p.rule_id for p in traza.steps]
    assert "RGI-3c" in aplicadas
    tres_c = next(p for p in traza.steps if p.rule_id == "RGI-3c")
    assert tres_c.candidate_codes[0].code == "8528"  # la última por numeración
    assert tres_c.confidence is not None
    assert tres_c.confidence < Decimal("0.8")


def test_lo_desempatado_por_rgi3c_sale_marcado_para_revision() -> None:
    """Resolver por orden de numeración no es resolver por una razón.

    La RGI 3 c) elige «la última partida por orden de numeración». Entre una
    computadora (8471) y un monitor (8528) elige el monitor, porque 8528 va
    después. El código es válido y la regla se aplica bien; lo que no hay es
    un motivo de fondo.

    Antes esto salía `RESOLVED` y con `requires_human_review` en `False`: la
    regla escribía «conviene revisión humana» en su `reasoning_summary` —que
    nadie lee en tiempo de ejecución— y la traza sólo miraba el estado final.
    La penalización de confianza tampoco bastaba, porque nada la usa de
    umbral. El resultado era el peor que puede dar este sistema: una
    clasificación equivocada con apariencia de fundada.

    El código se conserva a propósito. La RGI 3 c) es una regla real y el
    resultado que produce es el que prescribe: lo que cambia es que ya no se
    presenta como una conclusión limpia.
    """
    a = TariffCandidate(code="8471", text="Máquinas automáticas", level="HEADING", specificity=3)
    b = TariffCandidate(code="8528", text="Monitores", level="HEADING", specificity=3)
    # La subpartida y la fracción cuelgan de 8528 —la que gana el desempate—,
    # que es lo que permite a la RGI 6 llegar hasta el final. Con el catálogo
    # colgando de 8471 la secuencia moría antes y el fallo no se veía.
    sub = TariffCandidate(
        code="852859", text="Los demás monitores", level="SUBHEADING", specificity=3
    )
    frac = TariffCandidate(code="85285999", text="Los demás", level="FRACTION", specificity=3)

    traza = classify(contexto(), catalog=CatalogoFalso([a, b], [sub], [frac]), notes=NotasFalsas())

    assert "RGI-3c" in [p.rule_id for p in traza.steps]
    assert traza.final_status is RGIStatus.RESOLVED
    assert traza.resolved_code == "85285999"
    assert traza.requires_human_review, "un desempate por numeración no es una conclusión limpia"


def test_una_resolucion_limpia_no_pide_revision() -> None:
    """El control del test anterior: no se marca todo por si acaso.

    Marcar de más vacía de significado la bandeja de revisión — si todo pide
    revisión, nada la pide.
    """
    traza = classify(contexto(), catalog=catalogo_completo(), notes=NotasFalsas())

    assert "RGI-3c" not in [p.rule_id for p in traza.steps]
    assert traza.final_status is RGIStatus.RESOLVED
    assert not traza.requires_human_review


# ── Confianza ────────────────────────────────────────────────────────────────


def test_los_hechos_inferidos_bajan_la_confianza() -> None:
    """Un dato deducido por un modelo no sostiene igual que uno de la ficha."""
    solidos = classify(
        contexto(
            facts=(
                ProductFact(name="function", value="datos", status="OBSERVED"),
                ProductFact(name="weight", value="1.4 kg", status="OBSERVED"),
            )
        ),
        catalog=catalogo_completo(),
        notes=NotasFalsas(),
    )
    inferidos = classify(
        contexto(
            facts=(
                ProductFact(name="function", value="datos", status="INFERRED"),
                ProductFact(name="weight", value="1.4 kg", status="INFERRED"),
            )
        ),
        catalog=catalogo_completo(),
        notes=NotasFalsas(),
    )

    assert solidos.confidence is not None
    assert inferidos.confidence is not None
    assert inferidos.confidence < solidos.confidence


def test_la_confianza_del_conjunto_es_la_del_paso_mas_debil() -> None:
    """Una cadena no es más fiable que su eslabón más flojo."""
    traza = classify(contexto(), catalog=catalogo_completo(), notes=NotasFalsas())

    por_paso = [p.confidence for p in traza.steps if p.confidence is not None]
    assert traza.confidence == min(por_paso)


# ── El intérprete ayuda, no decide ───────────────────────────────────────────


def test_el_interprete_aporta_terminos_cuando_no_los_hay() -> None:
    """Traduce lenguaje comercial a lenguaje de nomenclatura."""
    traza = classify(
        contexto(search_terms=()),
        catalog=catalogo_completo(),
        notes=NotasFalsas(),
        interpreter=InterpreteFalso(terms=["máquina automática para tratamiento de datos"]),
    )

    assert traza.final_status is RGIStatus.RESOLVED


def test_el_motor_funciona_sin_interprete() -> None:
    """El LLM es opcional. Sin él hay menos alcance, no un fallo."""
    traza = classify(contexto(), catalog=catalogo_completo(), notes=NotasFalsas())

    assert traza.final_status is RGIStatus.RESOLVED


def test_la_traza_explica_por_que_se_descarto_cada_alternativa() -> None:
    """Lo que distingue una máquina de un prompt: el porqué de lo descartado."""
    a = TariffCandidate(code="8471", text="Máquinas automáticas", level="HEADING", specificity=3)
    b = TariffCandidate(code="8528", text="Monitores", level="HEADING", specificity=3)
    cat = CatalogoFalso([a, b], [SUB_847130], [FRAC_84713001])

    traza = classify(contexto(), catalog=cat, notes=NotasFalsas())

    descartes = traza.rejected()
    assert descartes
    assert any("RGI-1" in d for d in descartes)


# ── La especificidad no es evidencia (Persona 1, 28-sep) ───────────────────


_TALAVERA = TariffCandidate(code="69120003", text="De Talavera.", level="FRACTION", specificity=2)
_LOS_DEMAS = TariffCandidate(code="69120099", text="Los demás.", level="FRACTION", specificity=0)


def test_la_mas_especifica_no_gana_si_nada_la_sostiene() -> None:
    """Elegir «De Talavera» para una vajilla que no dice Talavera es afirmar
    una característica que el documento no sostiene.

    Pasó cinco veces contra la base: el agente aduanal y la declaración
    coincidían en «Los demás», y el motor proponía Talavera.
    """
    from core.rgi_engine.rules import _unica_o_mas_especifica

    elegida = _unica_o_mas_especifica(
        [_TALAVERA, _LOS_DEMAS],
        mercancia="VAJILLA DE CERAMICA VIDRIADA, NO PORCELANA, PARA SERVICIO DE MESA",
    )

    assert elegida is None, "sin respaldo, decide una persona"


def test_la_mas_especifica_gana_cuando_la_mercancia_la_respalda() -> None:
    """Si la mercancía SÍ dice Talavera, la específica es la correcta y el
    motor no tiene por qué mandarla a revisión."""
    from core.rgi_engine.rules import _unica_o_mas_especifica

    elegida = _unica_o_mas_especifica(
        [_TALAVERA, _LOS_DEMAS],
        mercancia="VAJILLA DE TALAVERA DE PUEBLA, PINTADA A MANO",
    )

    assert elegida is not None
    assert elegida.code == "69120003"


def test_el_respaldo_ignora_acentos_y_mayusculas() -> None:
    """La mercancía viene en mayúsculas y sin acentos; la tarifa los lleva."""
    from core.rgi_engine.rules import _unica_o_mas_especifica

    inoxidable = TariffCandidate(
        code="73239305", text="De acero inoxidable.", level="FRACTION", specificity=2
    )
    otra = TariffCandidate(code="73239999", text="Los demás.", level="FRACTION", specificity=0)

    elegida = _unica_o_mas_especifica(
        [inoxidable, otra], mercancia="SARTEN DE ACERO INOXIDABLE PARA COCINA"
    )

    assert elegida is not None
    assert elegida.code == "73239305"


# ── La materia de una hermana descarta (Persona 1, 5-oct) ──────────────────
#
# Las cuatro subpartidas de 7324, con el guion ya puesto delante (ADR 0004).

_FREGADERO_INOX = TariffCandidate(
    code="732410",
    text="Fregaderos (piletas de lavar) y lavabos, de acero inoxidable.",
    level="SUBHEADING",
    specificity=2,
)
_BANERA_FUNDICION = TariffCandidate(
    code="732421",
    text="Bañeras. De fundición, incluso esmaltadas.",
    level="SUBHEADING",
    specificity=2,
    group_text="Bañeras:",
)
_BANERA_DEMAS = TariffCandidate(
    code="732429",
    text="Bañeras. Las demás.",
    level="SUBHEADING",
    specificity=0,
    group_text="Bañeras:",
)
_HIGIENE_DEMAS = TariffCandidate(
    code="732490", text="Los demás, incluidas las partes.", level="SUBHEADING", specificity=0
)

_HERMANAS_7324 = [_FREGADERO_INOX, _BANERA_FUNDICION, _BANERA_DEMAS, _HIGIENE_DEMAS]


def _contexto_fregadero(**cambios: object) -> ClassificationContext:
    base: dict[str, object] = {
        "description": (
            "FREGADERO DE ACERO INOXIDABLE AISI 304, UNA TINA, 600 X 500 X 220 MM, "
            "ESPESOR 0.8 MM, PARA INSTALACION EN COCINA"
        ),
        "operation_date": OPERACION,
        "facts": (
            ProductFact(name="material", value="acero inoxidable AISI 304", status="OBSERVED"),
        ),
        "search_terms": ("fregaderos",),
    }
    base.update(cambios)
    return ClassificationContext(**base)  # type: ignore[arg-type]


def test_la_fundicion_se_descarta_porque_una_hermana_dice_inoxidable() -> None:
    """EL CASO QUE DESATASCA 15 PARTIDAS DEL CORPUS.

    732410 y 732421 empataban en especificidad —dos calificativos cada una— y
    el motor se negaba a elegir, con razón: contar calificativos no es una
    razón que nadie firme.

    Pero no hacía falta elegir, hacía falta descartar. La LIGIE abrió DOS
    hermanas por materia, y al hacerlo dijo que aquí la materia separa. Un
    fregadero de acero inoxidable no puede ser el de fundición.
    """
    from core.rgi_engine.rules import _la_materia_de_una_hermana_descarta

    posibles = _la_materia_de_una_hermana_descarta(_HERMANAS_7324, _contexto_fregadero())

    assert [c.code for c in posibles] == ["732410", "732429", "732490"]
    assert "732421" not in [c.code for c in posibles], "la de fundición es imposible"


def test_las_demas_nunca_se_descarta_por_materia() -> None:
    """No afirma ninguna materia, así que no hay nada que contradecir.

    Y es justo la que recoge lo que no encaja en las otras: descartarla
    dejaría al motor sin la posición residual que la tarifa puso para eso.
    """
    from core.rgi_engine.rules import _la_materia_de_una_hermana_descarta

    posibles = _la_materia_de_una_hermana_descarta(_HERMANAS_7324, _contexto_fregadero())

    assert "732429" in [c.code for c in posibles]
    assert "732490" in [c.code for c in posibles]


def test_sin_hermana_que_reclame_la_materia_no_se_descarta_nada() -> None:
    """LA PUERTA QUE HACE SEGURA ESTA REGLA.

    Si ninguna hermana nombra la materia de la ficha, la tarifa no está
    distinguiendo por materia en este nivel. Descartar ahí sería quitar la
    posición correcta por no repetir una palabra — el mismo error que clasificó
    un cable en «De acero sin recubrimiento» por compartir «acero».
    """
    from core.rgi_engine.rules import _la_materia_de_una_hermana_descarta

    ficha = _contexto_fregadero(
        facts=(ProductFact(name="material", value="aluminio anodizado", status="OBSERVED"),)
    )
    posibles = _la_materia_de_una_hermana_descarta(_HERMANAS_7324, ficha)

    assert len(posibles) == len(_HERMANAS_7324), "ninguna hermana habla de aluminio"


def test_sin_materia_declarada_no_se_descarta_nada() -> None:
    """Sin hecho sólido de materia no hay afirmación contra la que contradecir."""
    from core.rgi_engine.rules import _la_materia_de_una_hermana_descarta

    ficha = _contexto_fregadero(facts=())
    assert len(_la_materia_de_una_hermana_descarta(_HERMANAS_7324, ficha)) == 4


def test_la_materia_no_sale_de_la_descripcion_comercial() -> None:
    """Un cable de acero con alma de fibra nombra dos materias en su
    descripción, y adivinar cuál manda descartaría la posición correcta.

    Mismo criterio que `_familia_de_la_mercancia`, y por la misma razón.
    """
    from core.rgi_engine.rules import _la_materia_de_una_hermana_descarta

    ficha = _contexto_fregadero(
        description="BAÑERA DE FUNDICION ESMALTADA",
        facts=(),
    )
    assert len(_la_materia_de_una_hermana_descarta(_HERMANAS_7324, ficha)) == 4


def test_el_acero_inoxidable_es_acero() -> None:
    """Una posición que dice «de acero» le sirve a un inoxidable.

    La fundición no: la LIGIE las separa, y el inoxidable no es fundición.
    """
    from core.rgi_engine.rules import _la_materia_de_una_hermana_descarta

    de_acero = TariffCandidate(
        code="732420", text="De acero, sin más precisión.", level="SUBHEADING", specificity=1
    )
    posibles = _la_materia_de_una_hermana_descarta(
        [_FREGADERO_INOX, de_acero, _BANERA_FUNDICION], _contexto_fregadero()
    )

    assert [c.code for c in posibles] == ["732410", "732420"]


def test_la_materia_mas_larga_gana_al_leerla() -> None:
    """«acero inoxidable» tiene que reconocerse antes que «acero».

    Si no, el inoxidable se leería como acero a secas y la distinción que hace
    la tarifa se perdería justo al interpretarla.
    """
    from core.rgi_engine.rules import _materias_literales

    assert _materias_literales("De acero inoxidable.") == {"acero inoxidable"}
    assert _materias_literales("De fundición, incluso esmaltadas.") == {"fundicion"}
    assert _materias_literales("Las demás.") == set()


# ── Un CABLE es de los «Cables» (Persona 1, 5-oct) ─────────────────────────


def test_el_numero_gramatical_no_distingue_una_mercancia() -> None:
    """EL FALLO QUE BLOQUEABA 41 PRODUCTOS.

    La partida 7312 abre dos subpartidas: `731210` dice «Cables.» y `731290`
    dice «Los demás.». Cuarenta y un cables de acero del corpus se quedaban
    sin clasificar porque la ficha dice «CABLE» y la tarifa «Cables», y la
    comparación era de conjuntos exactos:

        {'cables'} & {'cable', 'acero', 'construccion', ...} = set()

    El motor no podía ver que un CABLE es uno de los «Cables».
    """
    from core.rgi_engine.rules import _algo_la_sostiene

    cables = TariffCandidate(code="731210", text="Cables.", level="SUBHEADING", specificity=3)
    assert _algo_la_sostiene(
        cables, "CABLE DE ACERO GALVANIZADO, CONSTRUCCION 6X19, DIAMETRO 10 MM"
    )


def test_el_plural_tambien_casa_al_reves() -> None:
    """La tarifa a veces va en singular y la ficha en plural."""
    from core.rgi_engine.rules import _algo_la_sostiene

    pos = TariffCandidate(code="821599", text="Cuchara de mesa.", level="FRACTION", specificity=2)
    assert _algo_la_sostiene(pos, "JUEGO DE CUCHARAS DE MESA DE ACERO INOXIDABLE")


def test_no_se_usa_la_raiz_de_seis_para_el_plural() -> None:
    """Son dos problemas distintos y cada uno tiene su herramienta.

    `_RAIZ = 6` está medido contra los pares que importan —soldadura/soldada—
    y una palabra de cinco letras truncada a seis sigue siendo ella misma:
    `cable` no se acerca a `cables` por ahí.
    """
    from core.rgi_engine.rules import _raices, _singulares

    assert _raices("Cables.") & _raices("CABLE") == set(), "la raíz no lo resuelve"
    assert "cable" in _singulares("cables"), "el singular sí"


def test_una_palabra_corta_no_se_destroza_al_singularizar() -> None:
    """Se quita la `s` sólo si lo que queda sigue siendo distintivo.

    El umbral hace de guardia: una palabra que al perder la `s` baja de cinco
    letras no se recorta, porque el trozo ya no distingue nada.
    """
    from core.rgi_engine.rules import _singulares

    assert _singulares("llaves") == {"llaves", "llave"}
    assert _singulares("redes") == {"redes"}, "«red» tiene tres letras: no se toca"
    assert _singulares("acero") == {"acero"}, "no acaba en s"


def test_el_plural_no_inventa_coincidencias() -> None:
    """Dos palabras distintas no se vuelven la misma al singularizar."""
    from core.rgi_engine.rules import _palabras_con_singular

    assert not (_palabras_con_singular("tornillos") & _palabras_con_singular("tuercas"))
    assert not (_palabras_con_singular("alambres") & _palabras_con_singular("alambique"))
