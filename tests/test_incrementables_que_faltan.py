"""`MISSING_INCREMENTABLE` (§25): la factura cobra flete y seguro aparte y la
partida declara menos incrementables (art. 65 de la Ley Aduanera)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.evaluation.deteccion import DETECTOR_POR_ERROR, SIN_DETECTOR
from core.shadow import DeclaredItem, DivergenceType, ExpectedItem, compare
from core.shadow.compare import _lagunas, comprobaciones_hechas

pytestmark = pytest.mark.unit


def _divergencias(declarados: str, minimo: str | None) -> list:  # type: ignore[type-arg]
    return [
        d
        for d in compare(
            [DeclaredItem(line_number=1, incrementables=Decimal(declarados))],
            [
                ExpectedItem(
                    line_number=1,
                    minimum_incrementables=Decimal(minimo) if minimo else None,
                    derivations={"incrementables": "(flete …) × FIX × parte = 4800.00"},
                )
            ],
        ).divergences
        if d.kind is DivergenceType.MISSING_INCREMENTABLE
    ]


def test_declarar_menos_que_el_flete_de_la_factura_es_hallazgo() -> None:
    [d] = _divergencias("1200.00", "4800.00")
    assert d.field == "incrementables"
    assert d.expected_value == "4800.00"
    assert "faltan 3600.00" in d.reasoning
    assert d.derivation and "FIX" in d.derivation
    assert d.severity == "HIGH"


def test_una_diferencia_de_redondeo_no_es_hallazgo() -> None:
    assert _divergencias("4799.00", "4800.00") == []


def test_declarar_de_mas_no_es_este_hallazgo() -> None:
    assert _divergencias("5000.00", "4800.00") == []


def test_sin_flete_en_la_factura_es_una_laguna_y_no_un_acierto() -> None:
    esperada = ExpectedItem(line_number=1)
    assert _divergencias("0", None) == []
    assert "incrementables" not in comprobaciones_hechas(esperada)
    assert any("incrementables" in r for r in _lagunas(esperada))


def test_la_medicion_ya_lo_cuenta_como_detector() -> None:
    assert DETECTOR_POR_ERROR["MISSING_INCREMENTABLE"] == "MISSING_INCREMENTABLE"
    assert "MISSING_INCREMENTABLE" not in SIN_DETECTOR
