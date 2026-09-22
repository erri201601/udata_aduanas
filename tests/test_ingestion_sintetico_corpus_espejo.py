"""Tests del parser del corpus espejo V1 (Tarea 1, Persona 2).

`unit` — no dependen de la red ni de MinIO. `tests/fixtures/corpus_espejo_v1_fragmento.py`
es un recorte literal del JSON real (sha256 documentado ahí), con tres
partidas reales del mismo pedimento: limpia, con una anomalía, y con
`classification_evaluable=false`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from ingestion.sintetico.corpus_espejo import ANOMALY_MAP, parse_corpus

from tests.fixtures.corpus_espejo_v1_fragmento import FRAGMENTO

pytestmark = pytest.mark.unit


def test_parse_corpus_extrae_el_documento_y_sus_tres_partidas() -> None:
    corpus = parse_corpus(FRAGMENTO)

    assert len(corpus.pedimentos) == 1
    ped = corpus.pedimentos[0]
    assert ped.document_id == "PED_SIM_001"
    assert ped.pedimento_number == "26 47 9999 600001"
    assert ped.trade_flow == "IMPORT"
    assert ped.date_entry == date(2026, 8, 3)
    assert ped.date_payment == date(2026, 8, 4)
    assert ped.exchange_rate == Decimal("18.33")
    assert ped.importer_rfc == "SIM260101AA"
    assert ped.provider_country == "CHN"
    assert ped.provider_currency == "USD"
    assert [p.sec for p in ped.parts] == ["004", "001", "009"]


def test_parse_corpus_partida_limpia_no_trae_anomalias() -> None:
    corpus = parse_corpus(FRAGMENTO)
    limpia = next(p for p in corpus.pedimentos[0].parts if p.sec == "004")

    assert limpia.anomalies == []
    assert limpia.expected == limpia.observed


def test_parse_corpus_partida_con_anomalia_nico() -> None:
    corpus = parse_corpus(FRAGMENTO)
    con_anomalia = next(p for p in corpus.pedimentos[0].parts if p.sec == "001")

    assert len(con_anomalia.anomalies) == 1
    anomalia = con_anomalia.anomalies[0]
    assert anomalia.code == "NICO_INCORRECTO"
    assert anomalia.expected_value == "01"
    assert anomalia.observed_value == "99"
    assert anomalia.error_type_y_campo == ("WRONG_NICO", None)
    assert anomalia.expected_detection is True
    # la diferencia real vive en observed, nunca se filtra a otro lado
    assert con_anomalia.observed["nico"] == "99"
    assert con_anomalia.expected["nico"] == "01"


def test_parse_corpus_partida_evaluable_false_conserva_spec_recortado() -> None:
    corpus = parse_corpus(FRAGMENTO)
    recortada = next(p for p in corpus.pedimentos[0].parts if p.sec == "009")

    assert recortada.classification_evaluable is False
    assert "espesor_pared_mm" not in recortada.technical_spec
    referencia = corpus.reference_specs[recortada.product_id]
    assert "espesor_pared_mm" in referencia
    faltantes = set(referencia) - set(recortada.technical_spec)
    assert faltantes == {"espesor_pared_mm"}


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("FRACCION_INCORRECTA", ("WRONG_FRACTION", None)),
        ("NICO_INCORRECTO", ("WRONG_NICO", None)),
        ("PAIS_ORIGEN_INCONSISTENTE", ("WRONG_ORIGIN", None)),
        ("UMC_INVALIDA", ("WRONG_UNIT", None)),
        ("CANTIDAD_UMC_INCONSISTENTE", ("INCONSISTENT_QUANTITY", None)),
        ("CAMPO_TECNICO_FALTANTE", ("MISSING_TECHNICAL_FIELD", None)),
        ("IGI_TASA_INCORRECTA", ("WRONG_VALUE", "igi_rate")),
        ("IVA_BASE_INCORRECTA", ("WRONG_VALUE", "iva_base")),
        ("IVA_IMPORTE_INCORRECTO", ("WRONG_VALUE", "iva_amount")),
        ("VALOR_ADUANA_INCONSISTENTE", ("WRONG_VALUE", "customs_value")),
    ],
)
def test_anomaly_map_cubre_los_diez_tipos_del_mapeo_de_persona_1(
    codigo: str, esperado: tuple[str, str | None]
) -> None:
    assert ANOMALY_MAP[codigo] == esperado


def test_solo_cantidad_umc_inconsistente_es_indetectable() -> None:
    """Regresión (Persona 1, 21-sep-2026): las 6 anomalías de cantidad son
    indetectables a propósito -- el precio unitario del PDF se calculó con la
    cantidad ya alterada. Ninguna otra debe heredar ese comportamiento."""
    from ingestion.sintetico.corpus_espejo import ParsedAnomaly

    for codigo in ANOMALY_MAP:
        anomalia = ParsedAnomaly(code=codigo, field="x", expected_value="a", observed_value="b")
        esperado_detection = codigo != "CANTIDAD_UMC_INCONSISTENTE"
        assert anomalia.expected_detection is esperado_detection


def test_parse_corpus_falla_ruidoso_si_falta_una_clave_esperada() -> None:
    incompleto = {"ground_truth": {"X": {}}, "product_specs": {}}

    with pytest.raises(KeyError):
        parse_corpus(incompleto)
