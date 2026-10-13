"""El NICO en la salida de la clasificación (§19) y su medición (§39).

Lo que se protege: que el NICO sólo salga cuando la LIGIE no deja elección,
que nunca acompañe a una fracción no defendible, y que la medición lo cuente
sólo donde la fracción acertó.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from apps.evaluacion.clasificacion_39 import medir
from core.classification import nico_de
from database.repositories.classification import _razonamiento

from tests.test_classification_orchestrator import clasificar

pytestmark = pytest.mark.unit

HOY = date(2026, 10, 13)


class Nicos:
    def __init__(self, por_fraccion: dict[str, tuple[str, ...] | None]) -> None:
        self.por_fraccion = por_fraccion
        self.consultas: list[str] = []

    def nicos(self, *, on_date: date, fraction_code: str) -> tuple[str, ...] | None:
        self.consultas.append(fraction_code)
        return self.por_fraccion.get(fraction_code)


# ── La regla ─────────────────────────────────────────────────────────────────


def test_con_un_unico_nico_no_hay_nada_que_elegir() -> None:
    nico, motivo = nico_de(Nicos({"84713001": ("00",)}), on_date=HOY, fraction_code="84713001")
    assert nico == "00"
    assert "único NICO" in motivo


def test_con_varios_no_se_elige_y_se_dicen_cuales() -> None:
    nico, motivo = nico_de(
        Nicos({"73121099": ("01", "02", "99")}), on_date=HOY, fraction_code="73121099"
    )
    assert nico is None
    assert "3 NICO" in motivo and "01, 02, 99" in motivo


def test_sin_nico_cargados_no_se_inventa_el_00() -> None:
    nico, motivo = nico_de(Nicos({"84713001": ()}), on_date=HOY, fraction_code="84713001")
    assert nico is None
    assert "no tiene NICO cargados" in motivo


def test_una_fraccion_no_vigente_no_tiene_nico() -> None:
    nico, motivo = nico_de(Nicos({}), on_date=HOY, fraction_code="84713001")
    assert nico is None
    assert "no está vigente" in motivo


# ── En el orquestador ────────────────────────────────────────────────────────


def test_la_clasificacion_entrega_el_nico_unico() -> None:
    r = clasificar(nicos=Nicos({"84713001": ("00",)}))
    assert r.code == "84713001"
    assert r.nico == "00"
    assert r.to_decision_fields()["nico_code"] == "00"
    assert "NICO: único NICO" in _razonamiento(r)


def test_sin_catalogo_de_nico_no_se_intenta() -> None:
    r = clasificar()
    assert r.code == "84713001"
    assert r.nico is None and r.nico_reason is None


def test_una_fraccion_no_defendible_no_lleva_nico() -> None:
    catalogo = Nicos({"84713001": ("00",)})
    r = clasificar(legal_refs=[], nicos=catalogo)
    assert r.code is None
    assert r.nico is None
    assert r.to_decision_fields()["nico_code"] is None
    assert catalogo.consultas == [], "ni se consulta: no hay fracción que sostener"


def test_con_varios_nico_el_razonamiento_dice_por_que_no_hay() -> None:
    r = clasificar(nicos=Nicos({"84713001": ("01", "02")}))
    assert r.nico is None
    assert "2 NICO vigentes" in _razonamiento(r)


# ── La medición ──────────────────────────────────────────────────────────────


def _fila(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "sku": "PED_SIM_001-001",
        "declarada": "73051291",
        "propuesta": "73051291",
        "dictamen": None,
        "sin_fundamento": False,
        "hubo_decision": True,
        "dictamen_nico": None,
        "declarada_nico": "02",
        "fecha": HOY,
    }
    base.update(kw)
    return type("Fila", (), base)()


class SesionDeFilas:
    def __init__(self, filas: list[Any]) -> None:
        self._filas = filas

    def execute(self, _consulta: Any) -> Any:
        r = type("R", (), {})()
        r.all = lambda: list(self._filas)
        return r


def _medir(filas: list[Any], nicos: dict[str, tuple[str, ...] | None]) -> Any:
    return medir(SesionDeFilas(filas), Nicos(nicos))  # type: ignore[arg-type]


def test_mide_el_nico_cuando_la_fraccion_acerto() -> None:
    r = _medir([_fila()], {"73051291": ("02",)})
    assert (r.nico_acerto, r.nico_fallo, r.nico_se_abstuvo) == (1, 0, 0)


def test_con_varios_nico_cuenta_como_abstencion() -> None:
    r = _medir([_fila()], {"73051291": ("01", "02")})
    assert r.nico_se_abstuvo == 1


def test_el_nico_del_dictamen_manda_sobre_el_declarado() -> None:
    r = _medir([_fila(dictamen="73051291", dictamen_nico="01")], {"73051291": ("02",)})
    assert r.nico_fallo == 1
    assert r.errores_nico == [("PED_SIM_001-001", "01", "02")]


def test_si_la_fraccion_fallo_el_nico_no_se_mide() -> None:
    r = _medir([_fila(propuesta="73051299")], {"73051299": ("02",)})
    assert r.fallo == 1
    assert r.nico_medibles == 0
