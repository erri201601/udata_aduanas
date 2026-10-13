"""Tests de `ingestion.dof.apendice_8_requisitos`: las 9 claves verificadas
a mano contra `pedimento_identifiers.supuestos_de_aplicacion` (no contra el
resumen de `docs/RECONOCIMIENTO_APENDICE_8.md`, que se equivocó en una)."""

from __future__ import annotations

import pytest
from ingestion.dof.apendice_8_requisitos import requisitos_apendice_8

pytestmark = pytest.mark.unit


def test_son_nueve_no_diez() -> None:
    filas = requisitos_apendice_8()

    assert len(filas) == 9


def test_af_no_entra_porque_no_nombra_una_clave_concreta() -> None:
    filas = requisitos_apendice_8()

    assert "AF" not in {f.identifier_code for f in filas}


def test_td_exige_k1_no_td() -> None:
    """El reconocimiento del 6-oct citó TD->TD; el texto real dice K1."""
    filas = requisitos_apendice_8()
    (fila,) = [f for f in filas if f.identifier_code == "TD"]

    assert fila.pedimento_key == "K1"


def test_las_ocho_restantes_son_auto_referentes() -> None:
    filas = requisitos_apendice_8()
    auto_referentes = [f for f in filas if f.identifier_code != "TD"]

    assert len(auto_referentes) == 8
    for fila in auto_referentes:
        assert fila.identifier_code == fila.pedimento_key


def test_a3_y_td_no_citan_regla_el_resto_si() -> None:
    filas = requisitos_apendice_8()
    por_codigo = {f.identifier_code: f for f in filas}

    assert por_codigo["A3"].scope_note is None
    assert por_codigo["TD"].scope_note is None
    for codigo in ("V1", "V4", "V5", "V6", "V7", "V8", "V9"):
        assert por_codigo[codigo].scope_note is not None
