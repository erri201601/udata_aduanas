"""Tests de la fuente de dictámenes humanos.

Lo que se fija aquí es lo que distingue esta fuente de la del corpus: que sus
casos NO lleven verdad de modelo —son lo único que mide precisión— y que un
dictamen sin fracción no se cuele como si midiera una clasificación.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from apps.evaluacion.dictamenes_como_fuente import DictamenesHumanos
from core.evaluation.ports import FuenteDeCasos

pytestmark = pytest.mark.unit


class SesionFalsa:
    def __init__(self, filas: list[Any]) -> None:
        self._filas = filas

    def execute(self, _consulta: Any) -> Any:
        return SimpleNamespace(all=lambda: self._filas)


def _dictamen(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid.UUID("11111111-1111-4111-8111-111111111111"),
        "fraction_code": "69111001",
        "operation_date": date(2026, 8, 3),
        "summary": "JUEGO DE VAJILLA DE PORCELANA PARA SERVICIO DE MESA",
        "data_origin": "SYNTHETIC",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _fuente(filas: list[Any] | None = None) -> DictamenesHumanos:
    return DictamenesHumanos(SesionFalsa(filas if filas is not None else [_dictamen()]))  # type: ignore[arg-type]


def test_cumple_el_puerto_del_harness() -> None:
    assert isinstance(_fuente(), FuenteDeCasos)


def test_un_dictamen_no_lleva_verdad_de_modelo() -> None:
    """Es la diferencia entre medir precisión y medir parecido.

    Si esta fuente marcara verdad_de_modelo, el reporte declararía el mismo
    límite que el corpus y no habría forma de saber que aquí sí se mide.
    """
    (caso,) = list(_fuente().casos())

    assert caso.verdad_de_modelo is False
    assert caso.hs6_esperado == "691110"


def test_la_mercancia_sigue_siendo_sintetica() -> None:
    """El juicio es humano; el producto del corpus no lo es.

    Con data_origin del dictamen, el reporte dejaría de avisar de que esto no
    es una medición de producción (§33): mentiría por omisión.
    """
    (caso,) = list(_fuente().casos())

    assert caso.data_origin == "SYNTHETIC"


def test_un_dictamen_sin_fraccion_no_mide_una_clasificacion() -> None:
    """Confirmar que NO se puede clasificar es un juicio válido, y no un código.

    Colarlo como caso compararía contra un vacío.
    """
    filas = [_dictamen(), _dictamen(fraction_code=None), _dictamen(summary=None)]

    assert len(list(_fuente(filas).casos())) == 1


def test_sin_dictamenes_no_inventa_casos() -> None:
    """Hoy es el caso real: 22 decisiones pendientes y cero veredictos."""
    assert list(_fuente([]).casos()) == []


def test_el_identificador_lleva_a_la_decision() -> None:
    """Un desacuerdo contra un humano hay que poder ir a mirarlo."""
    (caso,) = list(_fuente().casos())

    assert caso.identificador == "11111111-1111-4111-8111-111111111111"
