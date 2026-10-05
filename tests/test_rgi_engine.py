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


# ── Una exclusión ajena no descarta (Persona 1, 5-oct) ─────────────────────

_TALAVERA_FR = TariffCandidate(
    code="69120003", text="De Talavera.", level="FRACTION", specificity=2
)
_EXCLUSION_REAL = (("ceramica vidriada", "talavera"),)


def _vajilla(descripcion: str, material: str) -> ClassificationContext:
    return ClassificationContext(
        description=descripcion,
        operation_date=OPERACION,
        facts=(ProductFact(name="material", value=material, status="OBSERVED"),),
        search_terms=("vajilla",),
        exclusiones=_EXCLUSION_REAL,
    )


def test_una_exclusion_de_otro_producto_no_descarta_esta_posicion() -> None:
    """EL DEFECTO MÁS GRAVE QUE QUEDABA, Y ESTABA VIVO EN LA BASE.

    Se comprobaba que el término de la TARIFA casara con la candidata y nunca
    que el término de la FICHA estuviera en esta ficha. Con la exclusión real
    que hay cargada —«cerámica vidriada» no es «talavera», firmada por un
    clasificador— una vajilla que SÍ es de Talavera perdía su fracción.

    Y la traza lo justificaba diciendo «la ficha dice "ceramica vidriada"»
    sobre una ficha que no dice eso. Un descarte equivocado que se escuda en el
    nombre de una persona es peor que no tener vocabulario.

    No lo cazó ninguna medición porque ningún producto limpio del corpus es de
    Talavera: la precisión se mantuvo en 100 % por cómo está compuesto el
    corpus, no porque esto estuviera bien.
    """
    from core.rgi_engine.rules import _lo_aprendido_la_descarta

    ficha = _vajilla("VAJILLA DE TALAVERA DE PUEBLA, PINTADA A MANO", "talavera")
    assert _lo_aprendido_la_descarta(_TALAVERA_FR, ficha) is None


def test_la_exclusion_sigue_valiendo_para_la_ficha_que_la_motivo() -> None:
    """La cautela no puede comerse el caso para el que se firmó."""
    from core.rgi_engine.rules import _lo_aprendido_la_descarta

    ficha = _vajilla("VAJILLA DE CERAMICA VIDRIADA, NO PORCELANA", "ceramica vidriada")
    motivo = _lo_aprendido_la_descarta(_TALAVERA_FR, ficha)
    assert motivo is not None
    assert "ceramica vidriada" in motivo


def test_media_coincidencia_no_arrastra_un_veredicto() -> None:
    """«Cerámica vidriada» es una respuesta sobre esas dos palabras JUNTAS.

    Con que bastara una, una ficha que sólo dijera «cerámica» cargaría con un
    veredicto que nadie dio sobre ella.
    """
    from core.rgi_engine.rules import _lo_aprendido_la_descarta

    ficha = _vajilla("PIEZA DE CERAMICA PARA HORNO INDUSTRIAL", "ceramica")
    assert _lo_aprendido_la_descarta(_TALAVERA_FR, ficha) is None


# ── «Excepto» niega igual que «sin» (Persona 1, 5-oct) ─────────────────────


def test_excepto_niega_como_sin() -> None:
    """LA MITAD DEL MECANISMO ESTABA SIN LEER.

    La 6912 dice «Vajilla […] de cerámica, EXCEPTO porcelana» y la 6911 dice
    «de porcelana». Una vajilla de porcelana va en la 6911, y el motor la metía
    en la 6912 —la que explícitamente la excluye— porque `_FAMILIAS` mete
    «porcelana» dentro de la familia «cerámica» y porque la 6912 NOMBRA la
    palabra en su cláusula de excepción, lo que la hacía parecer más compatible
    en vez de menos.

    «sin» aparece en 369 posiciones de la tarifa y «excepto» en 301.
    """
    from core.rgi_engine.rules import _contradice, _raices

    ceramica = TariffCandidate(
        code="6912",
        text=(
            "Vajilla y demás artículos de uso doméstico, higiene o tocador, "
            "de cerámica, excepto porcelana."
        ),
        level="HEADING",
        specificity=2,
    )
    afirmado = _raices("JUEGO DE VAJILLA DE PORCELANA PARA SERVICIO DE MESA")
    motivo = _contradice(ceramica, afirmado)
    assert motivo is not None, "una porcelana no puede caer en «excepto porcelana»"
    assert "excepto" in motivo and "porcelana" in motivo


def test_una_excepcion_que_repite_el_sujeto_no_niega() -> None:
    """LA GUARDA QUE EVITA DESCARTAR EL ARANCEL ENTERO.

        151710  «Margarina, excepto la margarina líquida.»

    Lo excluido es *líquida*, no *margarina*. Negar la segunda descartaría esa
    posición para toda la margarina. La palabra no puede aparecer en el resto
    del texto: si aparece, la posición habla de ella y la excepción la acota.
    """
    from core.rgi_engine.rules import _lo_que_excepciona

    assert _lo_que_excepciona("Margarina, excepto la margarina liquida.") is None
    assert _lo_que_excepciona("Harina de semillas, excepto la harina de mostaza.") is None


def test_una_excepcion_con_una_frase_en_medio_no_niega() -> None:
    """Entre «excepto» y la palabra sólo pueden ir artículos.

    Cualquier otra cosa significa que la excepción es una frase, y una frase no
    se niega con una palabra suelta.
    """
    from core.rgi_engine.rules import _lo_que_excepciona

    assert _lo_que_excepciona("Tubos, excepto los comprendidos en la fraccion 7304.") is None
    assert _lo_que_excepciona("Apio, excepto el apionabo.") == "apionabo"


def test_una_excepcion_sin_palabra_distintiva_no_niega() -> None:
    """«Caracoles, excepto los de mar»: «mar» no distingue nada."""
    from core.rgi_engine.rules import _lo_que_excepciona

    assert _lo_que_excepciona("Caracoles, excepto los de mar.") is None


def test_el_silencio_sigue_sin_ser_negacion() -> None:
    """La regla de siempre no se afloja: que la ficha no mencione algo no
    significa que no lo tenga."""
    from core.rgi_engine.rules import _contradice, _raices

    ceramica = TariffCandidate(
        code="6912",
        text="Vajilla de cerámica, excepto porcelana.",
        level="HEADING",
        specificity=2,
    )
    # Una ficha que NO dice de qué es: no se descarta nada.
    assert _contradice(ceramica, _raices("VAJILLA PARA SERVICIO DE MESA")) is None


# ── La ficha también niega (Persona 1, 5-oct) ──────────────────────────────


def _ficha(descripcion: str) -> ClassificationContext:
    return ClassificationContext(
        description=descripcion,
        operation_date=OPERACION,
        facts=(),
        search_terms=("x",),
    )


def test_un_cable_sin_recubrimiento_no_descarta_su_propia_fraccion() -> None:
    """EL DEFECTO MÁS VIEJO DE LOS ENCONTRADOS HOY.

        ficha     «CABLE DE ACERO SIN RECUBRIMIENTO»
        73121005  «De acero sin recubrimiento»

    Dicen LO MISMO y el motor los enfrentaba: «lo que la mercancía afirma» se
    construía con todas las palabras de la ficha, incluidas las que ella misma
    niega, así que la ficha quedaba afirmando «recubrimiento» y la fracción
    correcta se descartaba.

    Llevaba ahí desde que existe `_contradice` y nadie lo vio, porque no
    producía un fallo medido: hacía al motor abstenerse, no equivocarse.
    """
    from core.rgi_engine.rules import _contradice, _lo_que_la_ficha_afirma

    pos = TariffCandidate(
        code="73121005",
        text="De acero sin recubrimiento, con o sin lubricación.",
        level="FRACTION",
        specificity=1,
    )
    ficha = _ficha("CABLE DE ACERO SIN RECUBRIMIENTO, CONSTRUCCION 6X36, DIAMETRO 18 MM")
    assert _contradice(pos, _lo_que_la_ficha_afirma(ficha)) is None


def test_una_ficha_que_dice_no_porcelana_cabe_en_excepto_porcelana() -> None:
    """La tarifa dice «excepto porcelana» y la ficha dice «NO PORCELANA».

    Están de acuerdo. El motor los enfrentaba porque leía la palabra sin ver el
    «NO» de delante, y eso hundió la precisión de 100 % a 68 % en cuanto la
    regla de «excepto» hizo visible el error: ocho vajillas, el mismo fallo.
    """
    from core.rgi_engine.rules import _contradice, _lo_que_la_ficha_afirma

    pos = TariffCandidate(
        code="6912",
        text="Vajilla de cerámica, excepto porcelana.",
        level="HEADING",
        specificity=2,
    )
    ficha = _ficha("VAJILLA DE CERAMICA VIDRIADA, NO PORCELANA, PARA SERVICIO DE MESA")
    assert _contradice(pos, _lo_que_la_ficha_afirma(ficha)) is None


def test_una_ficha_que_si_afirma_porcelana_queda_excluida() -> None:
    """La simetría no puede comerse el descarte legítimo.

    Una vajilla DE porcelana no cabe en «de cerámica, excepto porcelana»: va en
    la 6911. Ésa es la mitad de la regla que corrige respuestas.
    """
    from core.rgi_engine.rules import _contradice, _lo_que_la_ficha_afirma

    pos = TariffCandidate(
        code="6912",
        text="Vajilla de cerámica, excepto porcelana.",
        level="HEADING",
        specificity=2,
    )
    ficha = _ficha("JUEGO DE VAJILLA DE PORCELANA PARA SERVICIO DE MESA, 24 PIEZAS")
    motivo = _contradice(pos, _lo_que_la_ficha_afirma(ficha))
    assert motivo is not None
    assert "porcelana" in motivo


def test_lo_negado_por_la_ficha_sale_de_lo_afirmado() -> None:
    """La cuenta, directa: lo que la ficha niega no está en lo que afirma."""
    from core.rgi_engine.rules import _lo_que_la_ficha_afirma, _raices

    afirma = _lo_que_la_ficha_afirma(_ficha("TUBO DE ACERO SIN COSTURA, SIN ALEAR"))
    assert _raices("costura") <= _raices("TUBO DE ACERO SIN COSTURA, SIN ALEAR")
    assert not (_raices("costura") & afirma), "la ficha NIEGA la costura"
    assert _raices("acero") & afirma, "pero sí afirma el acero"


# ── El bucle pregunta por lo que DIFIERE (Persona 1, 5-oct) ────────────────

_FRACCIONES_731210 = [
    TariffCandidate(
        code="73121007",
        text=(
            "Galvanizados, con un diámetro mayor a 4 mm pero inferior a 19 mm, "
            "constituidos por 7 alambres, lubricados."
        ),
        level="FRACTION",
        specificity=3,
    ),
    TariffCandidate(
        code="73121001",
        text=(
            "Galvanizados, con diámetro mayor de 4 mm, constituidos por más de 5 "
            "alambres y con núcleos sin torcer de la misma materia."
        ),
        level="FRACTION",
        specificity=1,
    ),
    TariffCandidate(
        code="73121005",
        text="De acero sin recubrimiento, con o sin lubricación.",
        level="FRACTION",
        specificity=1,
    ),
    TariffCandidate(code="73121099", text="Los demás.", level="FRACTION", specificity=0),
]


def _cable() -> ClassificationContext:
    return ClassificationContext(
        description="CABLE DE ACERO GALVANIZADO, CONSTRUCCION 6X19, DIAMETRO 10 MM, ALMA DE FIBRA",
        operation_date=OPERACION,
        facts=(
            ProductFact(name="material", value="acero galvanizado", status="OBSERVED"),
            ProductFact(name="construccion", value="6X19", status="OBSERVED"),
            ProductFact(name="diametro_mm", value="10", status="OBSERVED"),
        ),
        search_terms=("cables",),
    )


def test_el_bucle_pregunta_por_el_numero_de_alambres() -> None:
    """EL CASO QUE ATASCA 41 PRODUCTOS Y NO GENERABA NINGUNA PREGUNTA.

    El filtro anterior descartaba una candidata si CUALQUIER palabra suya
    aparecía en la ficha. La ficha dice «GALVANIZADO» y tres de las cuatro
    fracciones dicen «Galvanizados», así que todas parecían ya tocadas — y lo
    que no estaba resuelto era el número de alambres, que no se preguntaba
    nunca.

    «Galvanizados» la comparten tres: no distingue y no se pregunta por ella.
    «constituidos por 7 alambres» es de una sola, y es la duda.
    """
    from core.rgi_engine.pregunta import formular

    preguntas = formular(_cable(), _FRACCIONES_731210)
    exigencias = {p.codigo: p.exige for p in preguntas}

    assert "alambres" in exigencias.get("73121007", ""), "la duda es el número de alambres"
    assert "galvanizados" not in exigencias.get("73121007", "").casefold(), (
        "«Galvanizados» la comparten tres hermanas: no distingue nada"
    )


def test_no_se_pregunta_por_lo_que_el_motor_puede_medir() -> None:
    """«con un diámetro mayor a 4 mm pero inferior a 19 mm» lo evalúa
    `_condiciones` contra la ficha sin molestar a nadie.

    Preguntarlo es pedirle a una persona que haga una comparación numérica que
    la máquina hace sola.
    """
    from core.rgi_engine.pregunta import formular

    for p in formular(_cable(), _FRACCIONES_731210):
        assert "mayor a 4 mm" not in p.exige
        assert "inferior a 19" not in p.exige


def test_la_pregunta_no_empareja_un_atributo_a_dedo() -> None:
    """DOS HEURÍSTICAS DE EMPAREJADO, LAS DOS FALLARON.

    La pregunta elegía un atributo de la ficha para comparar con la cláusula
    legal. Medido sobre el corpus, producía basura:

        «¿es "caja 12 unidades" lo mismo que "Lana de hierro o acero"?»
        «¿es "10" lo mismo que "constituidos por 7 alambres"?»

    —embalaje contra materia, y el diámetro donde iba la construcción—. Se
    probaron dos criterios: «el atributo que el texto no menciona» y «el que
    aporta más palabras nuevas». Ninguno mide relevancia; miden lo contrario.

    Así que no se empareja: se pone delante la ficha entera y quien contesta
    hace el emparejado, que lo hace bien y en un segundo. Cuesta una línea más
    de lectura y no produce ninguna pregunta sin sentido, que es el único error
    que esto no puede permitirse.
    """
    from core.rgi_engine.pregunta import formular

    preguntas = formular(_cable(), _FRACCIONES_731210)
    assert preguntas, "el cable tiene que generar preguntas"
    for p in preguntas:
        # La ficha va completa, con sus tres hechos.
        assert "material" in p.mercancia
        assert "construccion" in p.mercancia
        assert "diametro_mm" in p.mercancia
        # Y la pregunta es sobre la cláusula, no sobre una pareja inventada.
        assert p.exige in p.texto
        assert "¿La cumple?" in p.texto


def test_no_se_pregunta_por_un_residual() -> None:
    """«Los demás» no exige nada: recoge lo que no cayó en sus hermanas, y no
    hay respuesta posible a «¿es tu mercancía "los demás"?»."""
    from core.rgi_engine.pregunta import formular

    assert "73121099" not in {p.codigo for p in formular(_cable(), _FRACCIONES_731210)}


def test_sin_candidatas_de_sobra_no_se_pregunta_nada() -> None:
    """Cuatro preguntas de sí o no no son una pregunta: son el trabajo entero.

    Ahí la respuesta honesta sigue siendo mandarlo a un clasificador.
    """
    from core.rgi_engine.pregunta import MAX_CANDIDATAS_PREGUNTABLES, formular

    demasiadas = _FRACCIONES_731210 * 2
    assert len(demasiadas) > MAX_CANDIDATAS_PREGUNTABLES
    assert formular(_cable(), demasiadas) == []


# ── Una respuesta no se derrama (Persona 1, 5-oct) ─────────────────────────


def test_una_respuesta_sobre_una_frase_no_descarta_a_las_hermanas() -> None:
    """LA TRAMPA QUE EL BUCLE DE PREGUNTAS HABRÍA TENDIDO A CÉSAR.

    Contestar «no» a «¿un estropajo de acero inoxidable cumple "Lana de hierro
    o acero"?» descartaba las TRES hermanas —732310, 732393 y 732394— porque
    la exclusión casaba por intersección de palabras y «acero» está en las
    tres. Y 732393 es «De acero inoxidable», justo la correcta.

    Es el mismo defecto que el #177 arregló entrando por otra puerta: una
    respuesta firmada descartando lo que nadie dijo, con el nombre de una
    persona en la traza.

    Una respuesta es sobre UNA frase de UNA posición.
    """
    from core.rgi_engine.rules import _lo_aprendido_la_descarta

    ficha = ClassificationContext(
        description="ESTROPAJO DE ACERO INOXIDABLE PARA LIMPIEZA DOMESTICA",
        operation_date=OPERACION,
        facts=(ProductFact(name="material", value="acero inoxidable", status="OBSERVED"),),
        search_terms=("estropajo",),
        exclusiones=(("acero inoxidable", "Lana de hierro o acero"),),
    )
    lana = TariffCandidate(
        code="732310",
        text="Lana de hierro o acero; esponjas, estropajos, guantes y artículos similares.",
        level="SUBHEADING",
        specificity=2,
    )
    inoxidable = TariffCandidate(
        code="732393", text="Los demás. De acero inoxidable.", level="SUBHEADING", specificity=2
    )

    assert _lo_aprendido_la_descarta(lana, ficha) is not None, "la preguntada sí"
    assert _lo_aprendido_la_descarta(inoxidable, ficha) is None, (
        "la correcta NO: comparten «acero» y eso no es una respuesta sobre ella"
    )


def test_un_termino_numerico_de_la_ficha_si_se_aplica() -> None:
    """«6x19» no tiene palabras distintivas y la exclusión era inerte.

    Se guardaba firmada y no se aplicaba nunca: alguien contestaba y no pasaba
    nada. Peor que no preguntar, porque gasta su tiempo y no se nota.
    """
    from core.rgi_engine.rules import _lo_aprendido_la_descarta

    ficha = ClassificationContext(
        description="CABLE DE ACERO GALVANIZADO, CONSTRUCCION 6x19, DIAMETRO 10 MM",
        operation_date=OPERACION,
        facts=(ProductFact(name="construccion", value="6x19", status="OBSERVED"),),
        search_terms=("cables",),
        exclusiones=(("6x19", "constituidos por 7 alambres"),),
    )
    siete = TariffCandidate(
        code="73121007",
        text="Galvanizados, constituidos por 7 alambres, lubricados.",
        level="FRACTION",
        specificity=3,
    )
    mas_de_cinco = TariffCandidate(
        code="73121001",
        text="Galvanizados, constituidos por más de 5 alambres y con núcleos sin torcer.",
        level="FRACTION",
        specificity=1,
    )

    assert _lo_aprendido_la_descarta(siete, ficha) is not None
    assert _lo_aprendido_la_descarta(mas_de_cinco, ficha) is None, (
        "«más de 5 alambres» es otra frase: 114 alambres la cumplen"
    )


def test_no_se_pregunta_cuando_la_ficha_cae_en_una_alternativa() -> None:
    """El punto y coma separa alternativas; la coma acumula condiciones.

    Un estropajo cae en la 732310 por «estropajos», pero la frase que la
    distingue es «Lana de hierro o acero» — y preguntar por ella tiene una
    respuesta natural que es «no». Contestado así se descarta la posición
    correcta: cierto sobre la frase, falso sobre la posición.
    """
    from core.rgi_engine.pregunta import formular

    ficha = ClassificationContext(
        description="ESTROPAJO DE ACERO INOXIDABLE PARA LIMPIEZA DOMESTICA",
        operation_date=OPERACION,
        facts=(
            ProductFact(name="material", value="acero inoxidable", status="OBSERVED"),
            ProductFact(name="tipo", value="estropajo", status="OBSERVED"),
        ),
        search_terms=("estropajo",),
    )
    lana = TariffCandidate(
        code="732310",
        text="Lana de hierro o acero; esponjas, estropajos, guantes y artículos similares.",
        level="SUBHEADING",
        specificity=2,
    )

    assert "732310" not in {p.codigo for p in formular(ficha, [lana])}


def test_las_condiciones_acumulativas_si_se_preguntan() -> None:
    """Sin punto y coma son condiciones que se exigen todas a la vez.

    Que la ficha cumpla «Galvanizados» no resuelve «constituidos por 7
    alambres», y callarse ahí deja 41 productos atascados para siempre.
    """
    from core.rgi_engine.pregunta import formular

    preguntas = formular(_cable(), _FRACCIONES_731210)
    assert "73121007" in {p.codigo for p in preguntas}


def test_no_se_pregunta_por_una_frase_que_permite_las_dos() -> None:
    """«con o sin lubricación» lo cumple un cable lubricado y uno seco.

    Preguntar «¿la cumple?» tiene una sola respuesta posible y no desatasca
    nada. El descarte por contradicción ya tenía esta guarda —`_NIEGA` lleva un
    `(?<!con o )`— y al generador le faltaba.
    """
    from core.rgi_engine.pregunta import formular

    lubricacion = TariffCandidate(
        code="73121005",
        text="De acero sin recubrimiento, con o sin lubricación.",
        level="FRACTION",
        specificity=1,
    )
    exigencias = {p.codigo: p.exige for p in formular(_cable(), [lubricacion])}
    assert "con o sin" not in exigencias.get("73121005", "")


# ── Si no se puede preguntar la subpartida, se pregunta la partida ─────────


def test_con_demasiadas_subpartidas_se_pregunta_por_la_partida() -> None:
    """LOS 44 PRODUCTOS QUE NO TENÍAN NINGUNA PREGUNTA NI SALIDA.

    `formular` se calla con más de cuatro candidatas, y hace bien: seis
    preguntas de sí o no no son una pregunta, son el trabajo entero. Pero
    callarse ahí dejaba sin salida a la olla de presión —seis subpartidas de
    8481— y al sartén —doce de 7318—.

    Y en esos casos el problema no está en la subpartida: está en la PARTIDA.
    Una olla de presión no es un «artículo de grifería». Preguntarlo es UNA
    pregunta en vez de seis, y es la que importa: un «no» tumba la partida
    entera y el motor deja de insistir en un sitio equivocado.
    """
    from core.rgi_engine.pregunta import formular

    griferia = TariffCandidate(
        code="8481",
        text=(
            "Artículos de grifería y órganos similares para tuberías, calderas, "
            "depósitos, cubas o continentes similares, incluidas las válvulas "
            "reductoras de presión."
        ),
        level="HEADING",
        specificity=2,
    )
    olla = ClassificationContext(
        description="OLLA DE PRESION DE ALUMINIO PARA USO DOMESTICO, CAPACIDAD 6 L",
        operation_date=OPERACION,
        facts=(
            ProductFact(name="material", value="aluminio", status="OBSERVED"),
            ProductFact(name="uso", value="domestico", status="OBSERVED"),
        ),
        search_terms=("presion",),
    )

    preguntas = formular(olla, [griferia])
    assert len(preguntas) == 1, "una pregunta sobre la partida, no seis sobre sus hijas"
    assert preguntas[0].codigo == "8481"
    assert "griferia" in _plano_test(preguntas[0].exige)


def _plano_test(texto: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore").decode()


# ── La partida correcta puede no llegar a ser candidata (César, 5-oct) ─────


def test_se_recupera_la_partida_que_cumple_un_umbral_medible() -> None:
    """EL DEFECTO QUE DESTAPÓ LA RESPUESTA DE UN CLASIFICADOR.

    `headings()` devuelve sólo las partidas que cubren MÁS términos, y eso
    evita que el ruido gane por la RGI 3 c) —un estropajo llegaba a tener
    sesenta candidatas y la 9605 se las ganaba—. Pero con los términos
    `TUBERIA ACERO CARBONO COSTURA HELICOIDAL DIAMETRO` de una tubería de
    ⌀1219 mm:

        7306, 7304, 8481, 3926   casan más términos        -> entran
        7305                     casa «acero» y «diametro» -> SE CORTA

    Y la 7305 es «tubos de sección circular con diámetro exterior superior a
    406.4 mm». Era la correcta y no competía.

    Mientras el motor se abstenía por el empate entre las que sí entraban, no
    se veía. Al contestar César que una tubería no es grifería y deshacerse el
    empate, el motor resolvió a la 7306 —el residual— con toda confianza: la
    precisión cayó de 100 % a 96.15 %.

    Se readmite por CUMPLIR el umbral de su propio texto, no por existir.
    """
    from core.rgi_engine.rules import _mas_la_que_cumple_una_condicion

    class CatalogoDeDosNiveles:
        """Devuelve 7306 con cobertura máxima y 7305 sólo si se pide más
        amplio, que es exactamente lo que hace la base."""

        def headings(
            self, *, on_date: object, terms: object, cobertura_minima: int | None = None
        ) -> list[TariffCandidate]:
            residual = TariffCandidate(
                code="7306",
                text="Los demás tubos y perfiles huecos, de hierro o acero.",
                level="HEADING",
                specificity=1,
            )
            if cobertura_minima is None:
                return [residual]
            return [
                residual,
                TariffCandidate(
                    code="7305",
                    text=(
                        "Los demás tubos de sección circular con diámetro exterior "
                        "superior a 406.4 mm, de hierro o acero."
                    ),
                    level="HEADING",
                    specificity=3,
                ),
            ]

        def subheadings(self, **_: object) -> list[TariffCandidate]:
            return []

        def fractions(self, **_: object) -> list[TariffCandidate]:
            return []

    tuberia = ClassificationContext(
        description="TUBERIA DE ACERO AL CARBONO, DIAMETRO EXTERIOR 1219 MM",
        operation_date=OPERACION,
        facts=(
            ProductFact(name="material", value="acero al carbono", status="OBSERVED"),
            ProductFact(name="diametro_exterior_mm", value="1219", status="OBSERVED"),
        ),
        search_terms=("tuberia",),
    )
    cat = CatalogoDeDosNiveles()
    partida = cat.headings(on_date=OPERACION, terms=("tuberia",))

    recuperadas = _mas_la_que_cumple_una_condicion(
        list(partida),
        cat,  # type: ignore[arg-type]
        tuberia,
        ("tuberia",),
    )
    assert {c.code for c in recuperadas} == {"7306", "7305"}, (
        "la 7305 fija un umbral que 1219 mm cumple: compite"
    )


def test_no_se_recupera_nada_sin_una_condicion_cumplida() -> None:
    """La puerta que impide reabrir el ruido del estropajo.

    Una partida se readmite por CUMPLIR un umbral de su propio texto, que es
    una afirmación sobre la mercancía. No por existir ni por compartir una
    palabra: eso es lo que hacía que la 9605 ganara.
    """
    from core.rgi_engine.rules import _mas_la_que_cumple_una_condicion

    class CatalogoSinUmbrales:
        def headings(
            self, *, on_date: object, terms: object, cobertura_minima: int | None = None
        ) -> list[TariffCandidate]:
            lana = TariffCandidate(
                code="7323",
                text="Lana de hierro o acero; esponjas, estropajos y artículos similares.",
                level="HEADING",
                specificity=2,
            )
            if cobertura_minima is None:
                return [lana]
            return [
                lana,
                TariffCandidate(
                    code="9605",
                    text="Juegos o surtidos de viaje para aseo personal.",
                    level="HEADING",
                    specificity=1,
                ),
            ]

        def subheadings(self, **_: object) -> list[TariffCandidate]:
            return []

        def fractions(self, **_: object) -> list[TariffCandidate]:
            return []

    estropajo = ClassificationContext(
        description="ESTROPAJO DE ACERO INOXIDABLE PARA LIMPIEZA DOMESTICA",
        operation_date=OPERACION,
        facts=(ProductFact(name="material", value="acero inoxidable", status="OBSERVED"),),
        search_terms=("estropajo",),
    )
    cat = CatalogoSinUmbrales()
    recuperadas = _mas_la_que_cumple_una_condicion(
        list(cat.headings(on_date=OPERACION, terms=("estropajo",))),
        cat,  # type: ignore[arg-type]
        estropajo,
        ("estropajo",),
    )
    assert {c.code for c in recuperadas} == {"7323"}, "la 9605 no cumple ningún umbral"


# ── Un residual no empata con la específica (César, 5-oct) ─────────────────


def test_un_residual_no_empata_con_la_posicion_especifica() -> None:
    """LO ENCONTRÓ UN CLASIFICADOR, NO UNA MEDICIÓN.

    La partida 7323 abre cinco subpartidas y el motor les daba la misma
    especificidad:

        732310  spec 2  grupo: —             «Lana de hierro o acero;
                                              esponjas, estropajos, guantes…»
        732393  spec 2  grupo: «Los demás:»  «Los demás. De acero inoxidable.»
        732394  spec 2  grupo: «Los demás:»  «Los demás. De hierro o acero…»

    La 732310 cuelga DIRECTA de la partida; las otras cuelgan de un grupo «Los
    demás:». Empataban, y el motor se negaba a elegir.

    En sus palabras: «el motor llegó correctamente a la partida 7323, pero no
    identificó que existe una subpartida específica para lana de hierro o
    acero, esponjas y estropajos: 7323.10. Por ello no debía continuar
    comparando 7323.94 como si fuera igualmente específica.»

    Un residual recoge lo que NO cayó en la específica. La LIGIE lo dice con la
    línea de guion y `group_text` ya la traía.
    """
    from core.rgi_engine.rules import _unica_o_mas_especifica

    estropajos = TariffCandidate(
        code="732310",
        text="Lana de hierro o acero; esponjas, estropajos, guantes y artículos similares.",
        level="SUBHEADING",
        specificity=2,
    )
    residual_inox = TariffCandidate(
        code="732393",
        text="Los demás. De acero inoxidable.",
        level="SUBHEADING",
        specificity=2,
        group_text="Los demás:",
    )
    residual_acero = TariffCandidate(
        code="732394",
        text="Los demás. De hierro o acero, esmaltados.",
        level="SUBHEADING",
        specificity=2,
        group_text="Los demás:",
    )

    elegida = _unica_o_mas_especifica(
        [estropajos, residual_inox, residual_acero],
        mercancia="ESTROPAJO DE ACERO INOXIDABLE PARA LIMPIEZA DOMESTICA",
    )
    assert elegida is not None, "ya no empatan: una es específica y dos son residuales"
    assert elegida.code == "732310"


def test_entre_residuales_el_desempate_sigue_como_estaba() -> None:
    """Si TODAS cuelgan de un residual, ninguna tiene ventaja.

    «Los demás. De acero inoxidable» sigue siendo más específica que «Los
    demás. Los demás» dentro de su propio grupo, y la regla no se mete ahí.
    """
    from core.rgi_engine.rules import _unica_o_mas_especifica

    inox = TariffCandidate(
        code="732393",
        text="Los demás. De acero inoxidable.",
        level="SUBHEADING",
        specificity=2,
        group_text="Los demás:",
    )
    los_demas = TariffCandidate(
        code="732399",
        text="Los demás. Los demás.",
        level="SUBHEADING",
        specificity=0,
        group_text="Los demás:",
    )

    elegida = _unica_o_mas_especifica(
        [inox, los_demas], mercancia="SARTEN DE ACERO INOXIDABLE PARA COCINA"
    )
    assert elegida is not None and elegida.code == "732393"


def test_solo_el_encabezado_decide_si_es_residual() -> None:
    """Se mira el grupo, no el texto propio.

    «Los demás. De acero inoxidable» empieza por «Los demás» en su texto
    completo porque el guion se le pone delante (ADR 0004). Lo que la hace
    residual es su ENCABEZADO, no esa repetición.
    """
    from core.rgi_engine.rules import _cuelga_de_un_residual

    sin_grupo = TariffCandidate(
        code="732310", text="Los demás tubos y perfiles huecos.", level="HEADING", specificity=1
    )
    assert not _cuelga_de_un_residual(sin_grupo), "sin encabezado no es residual"

    con_grupo = TariffCandidate(
        code="732393",
        text="De acero inoxidable.",
        level="SUBHEADING",
        specificity=2,
        group_text="Los demás:",
    )
    assert _cuelga_de_un_residual(con_grupo)


# ── Una respuesta firmada también descarta subpartidas (César, 5-oct) ───────


def _olla_de_aluminio(exclusiones: tuple[tuple[str, str], ...]) -> ClassificationContext:
    return ClassificationContext(
        description="ARTICULO PARA USO DOMESTICO; OLLA DE PRESIÓN DE ALUMINIO, 6 L",
        operation_date=OPERACION,
        facts=(
            ProductFact(name="tipo", value="olla de presion", status="OBSERVED"),
            ProductFact(name="uso", value="domestico/cocina", status="OBSERVED"),
        ),
        search_terms=("articulo", "domestico", "aluminio"),
        exclusiones=exclusiones,
    )


def _catalogo_7615() -> CatalogoFalso:
    """La partida 7615 y sus dos subpartidas, como están en la TIGIE."""
    return CatalogoFalso(
        headings=[
            TariffCandidate(
                code="7615",
                text=("Artículos de uso doméstico, higiene o tocador, y sus partes, de aluminio."),
                level="HEADING",
                specificity=4,
            )
        ],
        subheadings=[
            TariffCandidate(
                code="761510",
                text="Artículos de uso doméstico y sus partes; esponjas, estropajos.",
                level="SUBHEADING",
                specificity=2,
            ),
            TariffCandidate(
                code="761520",
                text="Artículos de higiene o tocador, y sus partes.",
                level="SUBHEADING",
                specificity=2,
            ),
        ],
        fractions=[
            TariffCandidate(
                code="76151002",
                text="Artículos de uso doméstico y sus partes.",
                level="FRACTION",
                specificity=2,
            )
        ],
    )


def test_una_respuesta_firmada_descarta_una_subpartida() -> None:
    """LA RESPUESTA DE SUBPARTIDA ERA INERTE, Y SE GUARDABA FIRMADA.

    `_lo_aprendido_la_descarta` se aplicaba a las fracciones y a las partidas,
    nunca a las subpartidas. César contestó el 5-oct que una olla de presión de
    cocina NO es «Artículos de higiene o tocador» —lo que hace imposible la
    761520 y deja sola a la 761510— y el motor siguió diciendo que las dos
    comprenden la mercancía y ninguna es más específica, con su respuesta ya
    guardada en la base.

    Tercera vez que aparece el mismo patrón: un dato que se escribe en el
    dominio y no se vuelve a leer.
    """
    traza = classify(
        _olla_de_aluminio((("domestico/cocina", "Artículos de higiene o tocador"),)),
        catalog=_catalogo_7615(),
        notes=NotasFalsas(),
    )

    assert traza.final_status is RGIStatus.RESOLVED
    assert traza.resolved_code == "76151002"


def test_el_descarte_por_respuesta_firmada_se_enseña_en_la_traza() -> None:
    """Un descarte que no se enseña es un candidato que desaparece.

    Y tiene que decir que viene de una respuesta, no de un algoritmo: quien
    audite ha de poder ver en qué se apoyó y quién lo firmó.
    """
    traza = classify(
        _olla_de_aluminio((("domestico/cocina", "Artículos de higiene o tocador"),)),
        catalog=_catalogo_7615(),
        notes=NotasFalsas(),
    )

    razon = traza.steps[-1].reasoning_summary or ""
    assert "761520" in razon
    assert "respuesta firmada" in razon


def test_sin_respuesta_la_olla_sigue_sin_resolverse() -> None:
    """El contraste: lo que resuelve el caso es la respuesta, no el cambio.

    Sin esta comprobación el test de arriba pasaría igual si la olla resolviera
    por cualquier otro motivo, y no probaría nada de lo que dice probar.
    """
    traza = classify(
        _olla_de_aluminio(()),
        catalog=_catalogo_7615(),
        notes=NotasFalsas(),
    )

    assert traza.final_status is RGIStatus.HUMAN_REVIEW_REQUIRED


def test_con_varias_supervivientes_el_descarte_no_desempata() -> None:
    """La regla que hace seguro descartar: sólo puede RESOLVER cuando queda una.

    Si quedaran varias y se desempatara por `specificity` entre las
    supervivientes, el motor convertiría una negativa honesta en una fracción
    elegida con menos candidatas — que es lo que ya salió mal con el cable
    6x19 en la RGI 3. Aquí la respuesta no descarta nada, quedan las dos, y la
    negativa se mantiene.
    """
    traza = classify(
        _olla_de_aluminio((("olla de presion", "Artículos de jardinería"),)),
        catalog=_catalogo_7615(),
        notes=NotasFalsas(),
    )

    assert traza.final_status is RGIStatus.HUMAN_REVIEW_REQUIRED


# ── Una pregunta que nadie puede contestar (5-oct) ──────────────────────────


def test_no_se_pregunta_por_una_referencia_a_otra_fraccion() -> None:
    """LA PREGUNTA MÁS RENTABLE DEL MOTOR NO TENÍA RESPUESTA.

    Medido el 5-oct sobre el corpus, la primera de la lista por rendimiento
    —14 casos, más que las otras dos juntas— era ésta:

        La tarifa exige: «excepto los comprendidos en la fracción
                          arancelaria 7312.10.08»
        ¿La cumple?      [sí / no]

    No es una característica del cable: es dónde está clasificado OTRO cable.
    Quien contesta tendría que resolver primero la 7312.10.08 —que es justo el
    empate que la pregunta venía a romper— y nada de lo que mire en la ficha se
    lo va a decir.

    `_lo_que_excepciona` ya se niega a NEGAR por una referencia cruzada, con
    este mismo criterio. Aquí faltaba, y el precio es peor: una exclusión
    inerte no molesta a nadie; una pregunta imposible gasta el tiempo del
    clasificador y encima parece trabajo hecho.
    """
    from core.rgi_engine.pregunta import formular

    cable = ClassificationContext(
        description="CABLE DE ACERO SIN RECUBRIMIENTO, CONSTRUCCION 6X36, DIAMETRO 18 MM",
        operation_date=OPERACION,
        facts=(ProductFact(name="construccion", value="6x36", status="OBSERVED"),),
        search_terms=("cables",),
    )
    candidatas = [
        TariffCandidate(
            code="73121005",
            text=(
                "De acero sin recubrimiento, con o sin lubricación, excepto los "
                "comprendidos en la fracción arancelaria 7312.10.08."
            ),
            level="FRACTION",
            specificity=3,
        ),
        TariffCandidate(
            code="73121008",
            text="Sin galvanizar, constituidos por 7 alambres.",
            level="FRACTION",
            specificity=3,
        ),
    ]

    for p in formular(cable, candidatas):
        assert "fracción" not in p.exige, f"pregunta por una referencia cruzada: {p.exige}"


def test_la_frase_que_si_distingue_se_sigue_preguntando() -> None:
    """Callarse en la referencia cruzada no es callarse del todo.

    El motor baja a la siguiente frase que sí distingue y sí se puede mirar en
    la ficha. Sin este test, la guarda podría dejar muda la pregunta entera y
    el caso quedaría sin salida, que es peor que una pregunta mala.
    """
    from core.rgi_engine.pregunta import formular

    cable = ClassificationContext(
        description="CABLE DE ACERO SIN RECUBRIMIENTO, CONSTRUCCION 6X36",
        operation_date=OPERACION,
        facts=(ProductFact(name="construccion", value="6x36", status="OBSERVED"),),
        search_terms=("cables",),
    )
    candidatas = [
        TariffCandidate(
            code="73121001",
            text="Galvanizados, con núcleos sin torcer de la misma materia.",
            level="FRACTION",
            specificity=3,
        ),
        TariffCandidate(
            code="73121005",
            text=(
                "De acero sin recubrimiento, excepto los comprendidos en la "
                "fracción arancelaria 7312.10.08."
            ),
            level="FRACTION",
            specificity=3,
        ),
    ]

    preguntas = formular(cable, candidatas)

    assert preguntas, "se calló del todo"
    assert all("fracción" not in p.exige for p in preguntas)
