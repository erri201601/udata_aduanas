"""Tests del parser del tipo de cambio FIX (`ingestion.banxico.fix`).

`unit`, sin red: usa el fragmento real de
`tests/fixtures/dof_fix_fragmento.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from ingestion.banxico.fix import (
    COD_TIPO_INDICADOR_DOLAR,
    CURRENCY,
    ParsedExchangeRate,
    fix_url,
    parse_fix_html,
)

from tests.fixtures.dof_fix_fragmento import FIX_FRAGMENTO_REAL

pytestmark = pytest.mark.unit


def test_parsea_las_cuatro_filas_reales() -> None:
    filas = parse_fix_html(FIX_FRAGMENTO_REAL)
    assert filas == [
        ParsedExchangeRate(currency="USD", rate_date=date(2026, 10, 1), rate=Decimal("18.069200")),
        ParsedExchangeRate(currency="USD", rate_date=date(2026, 10, 2), rate=Decimal("18.368800")),
        ParsedExchangeRate(currency="USD", rate_date=date(2026, 10, 5), rate=Decimal("18.190300")),
        ParsedExchangeRate(currency="USD", rate_date=date(2026, 10, 6), rate=Decimal("18.134300")),
    ]


def test_el_fin_de_semana_no_trae_fila_propia() -> None:
    """02 (viernes) y 05 (lunes) de octubre son consecutivos en la tabla --
    el 03 y 04 (sábado y domingo) no tienen fila, tal como el documento
    real los omite. No se inventa ninguna."""
    filas = parse_fix_html(FIX_FRAGMENTO_REAL)
    fechas = [f.rate_date for f in filas]
    assert date(2026, 10, 3) not in fechas
    assert date(2026, 10, 4) not in fechas


def test_un_rango_sin_filas_no_truena() -> None:
    assert parse_fix_html("<html><body>sin tabla aquí</body></html>") == []


def test_fix_url_usa_el_codigo_real_de_dolar_y_formato_dd_mm_aaaa() -> None:
    url = fix_url(start=date(2026, 9, 1), end=date(2026, 10, 6))
    assert f"cod_tipo_indicador={COD_TIPO_INDICADOR_DOLAR}" in url
    assert "dfecha=01/09/2026" in url
    assert "hfecha=06/10/2026" in url


def test_la_divisa_es_siempre_usd() -> None:
    assert CURRENCY == "USD"
