"""Cuotas verificadas el 26-oct: ollas de presión de China, tubería de la India (ADR 0027)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.routers import pedimentos
from ingestion.se import cuotas_compensatorias as cc

pytestmark = pytest.mark.unit


def test_la_cuota_de_ollas_no_cae_sobre_un_estropajo() -> None:
    """La única partida china 7615.10.02 del corpus es un estropajo sembrado ahí."""
    terminos = cc.ollas_de_presion_china()[0].product_terms

    assert pedimentos._la_partida_dice("OLLA DE PRESIÓN DE ALUMINIO, 6 L", terminos)
    assert not pedimentos._la_partida_dice("ESTROPAJO DE ACERO INOXIDABLE", terminos)
    assert not pedimentos._la_partida_dice("SARTEN DE ALUMINIO", terminos)


def test_sin_terminos_la_cuota_no_se_acota() -> None:
    assert pedimentos._la_partida_dice("CABLE DE ACERO", ())
    assert pedimentos._la_partida_dice(None, [])


def test_ollas_de_presion_92_64_desde_el_27_de_diciembre_de_2024() -> None:
    (fila,) = cc.ollas_de_presion_china()
    assert (fila.origin_country, fila.fraction_code) == ("CN", "76151002")
    assert (fila.rate, fila.rate_unit, fila.rate_currency) == ("92.64", "PCT", "XXX")
    assert (fila.valid_from, fila.valid_to) == (date(2024, 12, 27), date(2029, 12, 26))
    assert fila.exporter_name is None


def test_tuberia_india_128_24_por_tonelada_y_vigente_durante_el_examen() -> None:
    filas = cc.tuberia_india()
    assert {f.fraction_code for f in filas} == {"73051102", "73051291", "73051999"}
    for f in filas:
        assert (f.origin_country, f.rate, f.rate_unit) == ("IN", "128.24", "TNE")
        assert f.valid_from == date(2021, 4, 21)
        assert f.valid_to is None, "se cierra con la resolución final del examen, no antes"
        assert f.exporter_name is None, "Welspun y las demás: una sola tasa"


class _Sesion:
    """Sólo lo que toca `_cuota_compensatoria_esperada`."""


def _partida(**kw: Any) -> Any:
    base = {
        "country_of_origin": "CN",
        "declared_fraction_code": "76151002",
        "description": "OLLA DE PRESION DE ALUMINIO PARA USO DOMESTICO",
        "customs_value": Decimal("10000.00"),
        "commercial_unit": "6",
        "quantity": Decimal("10"),
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _fila_ollas() -> Any:
    (f,) = cc.ollas_de_presion_china()
    return SimpleNamespace(
        exporter_name=None,
        rate=Decimal(f.rate),
        rate_unit=f.rate_unit,
        product_terms=list(f.product_terms),
    )


def test_ad_valorem_es_tasa_por_valor_en_aduana(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pedimentos, "cuotas_vigentes", lambda *_a, **_k: [_fila_ollas()])
    monkeypatch.setattr(pedimentos, "_proveedor_legal_name", lambda *_a: None)

    aplica, monto = pedimentos._cuota_compensatoria_esperada(
        _Sesion(),  # type: ignore[arg-type]
        _partida(),
        date(2026, 8, 3),
    )

    assert aplica is True
    assert monto == Decimal("9264.00")


def test_otra_mercancia_en_la_misma_fraccion_no_sabe_de_cuota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«No se sabe», nunca «no aplica»: `(None, None)`, igual que sin fila."""
    monkeypatch.setattr(pedimentos, "cuotas_vigentes", lambda *_a, **_k: [_fila_ollas()])
    monkeypatch.setattr(pedimentos, "_proveedor_legal_name", lambda *_a: None)

    resultado = pedimentos._cuota_compensatoria_esperada(
        _Sesion(),  # type: ignore[arg-type]
        _partida(description="ESTROPAJO DE ACERO INOXIDABLE"),
        date(2026, 8, 3),
    )

    assert resultado == (None, None)
