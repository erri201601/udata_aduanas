"""Tests de la persistencia de clasificaciones.

Lo que se prueba aquí no es que las filas entren: es que lo que entra siga
diciendo la verdad. Una decisión mal persistida es peor que no persistirla —
parece auditable y no lo es.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from core.classification import classify_product
from core.evidence import DocumentRef
from core.product_dna import ExtractedAttribute, ProductDnaDraft
from core.rgi_engine import TariffCandidate

pytestmark = pytest.mark.unit

PARTIDA = TariffCandidate(
    code="8471",
    text="Máquinas automáticas para tratamiento de datos",
    level="HEADING",
    source_id="ligie",
    specificity=8,
)
ALTERNA = TariffCandidate(code="8528", text="Monitores", level="HEADING", specificity=3)
SUB = TariffCandidate(
    code="847130",
    text="Portátiles de peso inferior o igual a 10 kg",
    level="SUBHEADING",
    source_id="ligie",
    specificity=5,
)
FRACCION = TariffCandidate(
    code="84713001",
    text="Unidades de proceso digitales portátiles",
    level="FRACTION",
    source_id="ligie",
    specificity=5,
)
LIGIE = DocumentRef(
    document="LIGIE 2022 (DOF)",
    article="Capítulo 84",
    url="https://www.snice.gob.mx/",
    published_at=date(2022, 7, 7),
    content_hash="sha256:aaaa1111",
)


class Catalogo:
    def __init__(self, headings=None) -> None:  # type: ignore[no-untyped-def]
        self._h = headings if headings is not None else [PARTIDA]

    def headings(self, *, on_date, terms):  # type: ignore[no-untyped-def]
        return list(self._h)

    def subheadings(self, *, on_date, heading):  # type: ignore[no-untyped-def]
        return [SUB] if heading == "8471" else []

    def fractions(self, *, on_date, subheading):  # type: ignore[no-untyped-def]
        return [FRACCION]


class Notas:
    def notes_for(self, *, on_date, chapter):  # type: ignore[no-untyped-def]
        return []

    def excludes(self, *, on_date, heading, terms):  # type: ignore[no-untyped-def]
        return None


def resultado(*, headings=None, legal=True):  # type: ignore[no-untyped-def]
    dna = ProductDnaDraft(
        attributes=(
            ExtractedAttribute(
                name="function",
                value="tratamiento de datos",
                status="OBSERVED",
                confidence=Decimal("0.99"),
                locator="p.1",
            ),
            ExtractedAttribute(
                name="chassis",
                value="aluminio",
                status="INFERRED",
                confidence=Decimal("0.58"),
            ),
        ),
        summary="Computadora portátil de 14 pulgadas",
    )
    return classify_product(
        dna,
        operation_date=date(2024, 3, 15),
        catalog=Catalogo(headings),
        notes=Notas(),
        search_terms=("máquinas automáticas",),
        legal_refs=[(LIGIE, date(2022, 7, 7), "sha256:aaaa1111")] if legal else [],
    )


# ── Lo que se deriva, no se pide ─────────────────────────────────────────────


def test_los_niveles_salen_de_la_fraccion() -> None:
    """Pedirlos aparte abriría la puerta a que lleguen inconsistentes."""
    from database.repositories.classification import _niveles

    assert _niveles("84713001") == {
        "chapter": "84",
        "heading": "8471",
        "subheading": "847130",
        "fraction_code": "84713001",
    }


def test_sin_fraccion_defendible_no_se_guardan_niveles() -> None:
    """Guardar los niveles de una decisión rechazada daría la apariencia de
    una clasificación parcialmente válida, y no lo es."""
    from database.repositories.classification import _niveles

    assert _niveles(None) == {
        "chapter": None,
        "heading": None,
        "subheading": None,
        "fraction_code": None,
    }


def test_el_razonamiento_conserva_cada_paso() -> None:
    """Perderlo haría imposible responder «¿con qué regla?» del §49 con el
    detalle que pide una auditoría."""
    from database.repositories.classification import _razonamiento

    texto = _razonamiento(resultado())

    assert "RGI-1:" in texto
    assert "RGI-6:" in texto


def test_una_decision_bloqueada_lo_dice_en_el_razonamiento() -> None:
    from database.repositories.classification import _razonamiento

    texto = _razonamiento(resultado(legal=False))

    assert "NO DEFENDIBLE" in texto


def test_el_snapshot_guarda_con_que_datos_se_decidio() -> None:
    """§49: una decisión firmada tiene que poder explicarse con lo que se sabía
    entonces, no con lo que se sabe ahora."""
    from database.repositories.classification import _snapshot

    snap = _snapshot(resultado())

    assert snap["facts"]["function"] == "tratamiento de datos"
    assert snap["operation_date"] == "2024-03-15"
    assert "RGI-1" in snap["rules_evaluated"]


# ── Telemetría y el CHECK ────────────────────────────────────────────────────


def test_la_telemetria_se_copia_completa_o_no_se_copia() -> None:
    """`ck_classification_decisions_ai_call_complete` exige que si hay
    model_provider estén también el resto. Llenar sólo el proveedor haría
    fallar la inserción, y con razón."""
    from database.repositories.classification import _telemetria

    t = _telemetria(resultado())

    assert t, "hay un atributo INFERRED, así que hay evidencia de modelo"
    for campo in (
        "model_provider",
        "model_name",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "attempts",
    ):
        assert t[campo] is not None, f"{campo} vacío rompería el CHECK"


def test_sin_evidencia_de_modelo_no_se_inventa_telemetria() -> None:
    """Sin atributos inferidos no hubo llamada al modelo: los campos quedan
    vacíos, que es la verdad."""
    from database.repositories.classification import _telemetria

    dna = ProductDnaDraft(
        attributes=(
            ExtractedAttribute(name="function", value="datos", status="OBSERVED", locator="p.1"),
        ),
        summary="Laptop",
    )
    r = classify_product(
        dna,
        operation_date=date(2024, 3, 15),
        catalog=Catalogo(),
        notes=Notas(),
        search_terms=("máquinas",),
        legal_refs=[(LIGIE, date(2022, 7, 7), "sha256:aaaa1111")],
    )

    assert _telemetria(r) == {}


# ── Los candidatos: lo descartado es la mitad del valor ──────────────────────


def test_un_candidato_del_camino_no_figura_como_descartado() -> None:
    """La partida 8471 no fue rechazada: fue el camino hacia 84713001.

    Compararlo por igualdad estricta marcaría como rechazadas todas las
    partidas y subpartidas del camino ganador — y una traza que dice que
    descartó lo que eligió no explica nada.
    """
    r = resultado(headings=[PARTIDA, ALTERNA])
    codigos_en_camino = [
        c.code
        for p in r.trace.steps
        for c in p.candidate_codes
        if r.code and r.code.startswith(c.code)
    ]

    assert "8471" in codigos_en_camino
    assert "84713001" in codigos_en_camino
    assert "8528" not in codigos_en_camino


def test_el_descarte_lleva_su_motivo_real() -> None:
    """«No fue el más específico» sin decir frente a qué no ayuda a revisar."""
    from database.repositories.classification import _por_que_no

    r = resultado(headings=[PARTIDA, ALTERNA])
    motivo = _por_que_no(r, "8528")

    assert motivo
    assert "8528" in motivo or "partidas" in motivo


# ── La traza estructurada ────────────────────────────────────────────────────


def test_la_traza_guarda_una_entrada_por_regla() -> None:
    """El acta de CÓMO se decidió, congelada en la fila.

    Reejecutar el motor para explicar una decisión pasada daría un razonamiento
    distinto al que se firmó —la tarifa pudo cambiar—, y una auditoría que
    muestra otra cosa que lo firmado es peor que no tener auditoría.
    """
    from database.repositories.classification import _traza

    traza = _traza(resultado())

    assert [p["rule_id"] for p in traza] == ["RGI-1", "RGI-6"]
    assert all(p["status"] for p in traza)
    assert all(p["reasoning_summary"] for p in traza)


def test_la_traza_conserva_los_candidatos_de_cada_paso() -> None:
    """Sin ellos no se puede reconstruir qué alternativas había en cada punto."""
    from database.repositories.classification import _traza

    traza = _traza(resultado(headings=[PARTIDA, ALTERNA]))

    rgi1 = next(p for p in traza if p["rule_id"] == "RGI-1")
    assert set(rgi1["candidate_codes"]) == {"8471", "8528"}


def test_la_traza_es_serializable_a_json() -> None:
    """Va a una columna JSONB: un Decimal suelto rompería la inserción."""
    import json

    from database.repositories.classification import _traza

    json.dumps(_traza(resultado()))  # no debe lanzar
