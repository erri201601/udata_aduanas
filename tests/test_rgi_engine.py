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
