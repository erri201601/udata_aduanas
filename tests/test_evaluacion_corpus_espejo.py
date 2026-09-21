"""Tests del validador de corpus (`apps/evaluacion/corpus_espejo.py`).

`unit` — sin base de datos: el `Catalogo` se construye a mano. Lo que se
prueba es la lógica de validación, y para eso un catálogo de tres entradas
discrimina igual que uno de 8 136 y no depende de qué haya cargado hoy.

Cada test rompe el corpus de UNA forma y comprueba que el validador la caza.
El último es el que más importa: una anomalía legítimamente sembrada no es un
defecto del corpus, y confundirlas dejaría el validador inservible — rechazaría
exactamente los corpus que sirven.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from apps.evaluacion.corpus_espejo import Catalogo, informe, validar

pytestmark = pytest.mark.unit

CATALOGO = Catalogo(
    igi_por_fraccion={"73051291": Decimal("0.35"), "69111001": Decimal("0.15")},
    nicos=frozenset({("73051291", "01"), ("69111001", "00")}),
    unidades=frozenset({"3", "6", "12"}),
)

#: 900 + 100 = 1 000 de valor en aduana; IGI al 35% son 350; DTA 8 al millar
#: son 8; base de IVA 1 358; IVA al 16% son 217.28. Cuadra a mano.
_LIMPIA: dict[str, Any] = {
    "fraccion": "73051291",
    "nico": "01",
    "umc": "3",
    "cantidad_umc": 10,
    "igi_rate": 0.35,
    "precio_pagado_mxn": 900.0,
    "incrementables_mxn": 100.0,
    "valor_aduana_mxn": 1000.0,
    "dta_mxn": 8.0,
    "igi_mxn": 350.0,
    "iva_base_mxn": 1358.0,
    "iva_mxn": 217.28,
    "pais_origen": "CHN",
}


def _corpus(**cambios: Any) -> dict[str, Any]:
    """Un corpus de un pedimento y una partida, limpio salvo lo que se cambie."""
    partida = {
        "sec": "001",
        "expected": copy.deepcopy(_LIMPIA),
        "observed": copy.deepcopy(_LIMPIA),
        "anomalies": [],
    }
    partida.update(cambios)
    return {"ground_truth": {"PED_X": {"totals": {"valor_aduana_mxn": 1000.0}, "parts": [partida]}}}


def _comprobaciones(corpus: dict[str, Any]) -> list[str]:
    return [h.comprobacion for h in validar(corpus, CATALOGO)]


def test_un_corpus_limpio_no_tiene_defectos() -> None:
    assert validar(_corpus(), CATALOGO) == []


def test_caza_una_fraccion_que_no_existe() -> None:
    """Se cambian los dos lados: si sólo se tocara `expected`, el validador
    cazaría además —con razón— una partida limpia que difiere, y el test
    estaría probando dos cosas a la vez."""
    c = _corpus()
    for lado in ("expected", "observed"):
        c["ground_truth"]["PED_X"]["parts"][0][lado]["fraccion"] = "99999999"
    assert _comprobaciones(c) == ["fracción"]


def test_caza_un_nico_que_no_existe_en_esa_fraccion() -> None:
    c = _corpus()
    c["ground_truth"]["PED_X"]["parts"][0]["expected"]["nico"] = "07"
    assert "NICO" in _comprobaciones(c)


def test_caza_una_tasa_de_igi_que_no_es_la_de_la_tarifa() -> None:
    c = _corpus()
    c["ground_truth"]["PED_X"]["parts"][0]["expected"]["igi_rate"] = 0.25
    assert "IGI" in _comprobaciones(c)


def test_caza_una_umc_fuera_del_anexo_22() -> None:
    c = _corpus()
    c["ground_truth"]["PED_X"]["parts"][0]["expected"]["umc"] = "99"
    assert "UMC" in _comprobaciones(c)


def test_caza_un_iva_mal_calculado() -> None:
    c = _corpus()
    c["ground_truth"]["PED_X"]["parts"][0]["expected"]["iva_mxn"] = 200.0
    assert "aritmética" in _comprobaciones(c)


def test_caza_una_base_de_iva_que_olvida_el_dta() -> None:
    """El defecto exacto del primer juego de pedimentos que nos mandaron."""
    c = _corpus()
    partida = c["ground_truth"]["PED_X"]["parts"][0]["expected"]
    partida["iva_base_mxn"] = 1350.0  # valor + IGI, sin DTA
    partida["iva_mxn"] = 216.0
    assert _comprobaciones(c).count("aritmética") == 2


def test_caza_una_partida_limpia_que_si_difiere() -> None:
    """Un falso positivo que el motor no puede evitar: contamina la precisión."""
    c = _corpus()
    c["ground_truth"]["PED_X"]["parts"][0]["observed"]["nico"] = "99"
    assert _comprobaciones(c) == ["limpia contaminada"]


def test_caza_una_anomalia_que_no_altera_nada() -> None:
    """Un falso negativo imposible de detectar: contamina el recall."""
    c = _corpus()
    c["ground_truth"]["PED_X"]["parts"][0]["anomalies"] = [
        {"code": "NICO_INCORRECTO", "field": "nico", "expected": "01", "observed": "01"}
    ]
    assert _comprobaciones(c) == ["anomalía fantasma"]


def test_caza_un_encabezado_que_no_cuadra_con_sus_partidas() -> None:
    c = _corpus()
    c["ground_truth"]["PED_X"]["totals"]["valor_aduana_mxn"] = 1234.0
    assert _comprobaciones(c) == ["totales"]


def test_una_anomalia_bien_sembrada_no_es_un_defecto() -> None:
    """El test que impide que el validador rechace los corpus que sirven."""
    c = _corpus()
    partida = c["ground_truth"]["PED_X"]["parts"][0]
    partida["observed"]["nico"] = "99"
    partida["anomalies"] = [
        {"code": "NICO_INCORRECTO", "field": "nico", "expected": "01", "observed": "99"}
    ]
    assert validar(c, CATALOGO) == []


def test_el_informe_dice_si_es_apto_y_cuenta_las_anomalias() -> None:
    c = _corpus()
    c["ground_truth"]["PED_X"]["parts"][0]["observed"]["nico"] = "99"
    c["ground_truth"]["PED_X"]["parts"][0]["anomalies"] = [
        {"code": "NICO_INCORRECTO", "field": "nico", "expected": "01", "observed": "99"}
    ]
    texto = informe(c, validar(c, CATALOGO))
    assert "apto para cargarse" in texto
    assert "1  NICO_INCORRECTO" in texto
