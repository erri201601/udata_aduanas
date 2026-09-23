"""Tests de la fuente de casos del corpus espejo.

Lo que se fija aquí es lo que puede engañar a quien lea el número: que cada
caso declare que su verdad la decidió un modelo, que las partidas con la ficha
recortada no cuenten como fallo de clasificación, y que la verdad salga del
ground truth cuando la fracción fue mutada.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from apps.evaluacion.corpus_como_fuente import CorpusEspejo
from core.evaluation.ports import FuenteDeCasos

pytestmark = pytest.mark.unit


class SesionFalsa:
    """Devuelve las filas del ground truth primero y las partidas después."""

    def __init__(self, gt: list[Any], partidas: list[Any]) -> None:
        self._respuestas = [gt, partidas]

    def execute(self, _consulta: Any) -> Any:
        return SimpleNamespace(all=lambda: self._respuestas.pop(0))


def _partida(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": "p1",
        "line_number": 1,
        "declared_fraction_code": "73231001",
        "pedimento_number": "26 47 9999 600001",
        "operation_date": date(2026, 8, 3),
        "summary": "ESTROPAJO DE ACERO INOXIDABLE PARA LIMPIEZA DOMESTICA",
        "missing_information": [],
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _fuente(gt: list[Any] | None = None, partidas: list[Any] | None = None) -> CorpusEspejo:
    return CorpusEspejo(SesionFalsa(gt or [], partidas or [_partida()]))  # type: ignore[arg-type]


def test_cumple_el_puerto_del_harness() -> None:
    assert isinstance(_fuente(), FuenteDeCasos)


def test_cada_caso_declara_que_su_verdad_la_decidio_un_modelo() -> None:
    """Sin esto el reporte presentaría como precisión lo que es coincidencia."""
    (caso,) = list(_fuente().casos())

    assert caso.verdad_de_modelo is True
    assert caso.data_origin == "SYNTHETIC"


def test_la_fraccion_esperada_sale_del_ground_truth_cuando_fue_mutada() -> None:
    """En una partida con la fracción alterada, la declarada es la MALA."""
    gt = [SimpleNamespace(pedimento_item_id="p1", original_value="73239305")]

    (caso,) = list(_fuente(gt=gt, partidas=[_partida(declared_fraction_code="73269099")]).casos())

    assert caso.hs6_esperado == "732393", "se esperaba la verdad, no lo declarado"


def test_sin_anomalia_de_fraccion_la_declarada_es_la_esperada() -> None:
    (caso,) = list(_fuente().casos())

    assert caso.hs6_esperado == "732310"


def test_la_ficha_recortada_no_cuenta_como_fallo_de_clasificacion() -> None:
    """Ahí la respuesta correcta es pedir revisión humana, no un código.

    Contarlas mediría una decisión del corpus —recortó la ficha a propósito—
    y no al motor.
    """
    partidas = [_partida(), _partida(id="p2", missing_information=["descripcion_tecnica"])]

    casos = list(_fuente(partidas=partidas).casos())

    assert len(casos) == 1


def test_con_solo_evaluables_desactivado_entran_todas() -> None:
    """Para poder MIRAR qué hace el motor con una ficha incompleta."""
    partidas = [_partida(), _partida(id="p2", missing_information=["descripcion_tecnica"])]
    fuente = CorpusEspejo(SesionFalsa([], partidas), solo_evaluables=False)  # type: ignore[arg-type]

    assert len(list(fuente.casos())) == 2


def test_el_identificador_permite_encontrar_la_partida_despues() -> None:
    """Un desacuerdo hay que poder ir a mirarlo al pedimento."""
    (caso,) = list(_fuente().casos())

    assert caso.identificador == "26 47 9999 600001/1"
