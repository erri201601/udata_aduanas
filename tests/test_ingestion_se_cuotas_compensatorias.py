"""Tests de `ingestion.se.cuotas_compensatorias` (ADR 0009): los valores
verificados a mano contra el texto primario de la resolución EC 32-24
(DOF 2026-04-09), no contra un resumen de prensa."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from ingestion.se.cuotas_compensatorias import cable_de_acero_china

pytestmark = pytest.mark.unit


def test_las_cuatro_fracciones_de_la_resolucion() -> None:
    filas = cable_de_acero_china()

    assert {f.fraction_code for f in filas} == {
        "73121001",
        "73121005",
        "73121007",
        "73121099",
    }


def test_todas_son_origen_china_sin_exportador_nombrado() -> None:
    for fila in cable_de_acero_china():
        assert fila.origin_country == "CN"
        assert fila.exporter_name is None


def test_monto_y_vigencia_verbatim_del_punto_214() -> None:
    (fila,) = [f for f in cable_de_acero_china() if f.fraction_code == "73121099"]

    assert fila.rate == "2.58"
    assert fila.rate_currency == "USD"
    assert fila.rate_unit == "KG"
    assert fila.valid_from == date(2024, 12, 17)
    assert fila.valid_to == date(2029, 12, 17)


def test_el_rate_es_decimal_valido() -> None:
    for fila in cable_de_acero_china():
        Decimal(fila.rate)  # no debe lanzar
