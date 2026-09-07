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
