"""Una sola definición de «pendiente» (ADR 0008): la forma de la consulta.

Lo que hace la consulta contra datos de verdad lo prueba
`test_pendientes_integracion.py`. Aquí se fija lo que no puede cambiar sin que
nadie lo note: la unidad es la ficha, el dictamen es del caso, y no hay página.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from database.models import ClassificationDecision
from database.repositories.preguntas import pendientes, preguntas_de, productos_que_preguntaban
from sqlalchemy.dialects import postgresql

pytestmark = pytest.mark.unit

CLAUSULA = "constituidos por 7 alambres"


def _sql() -> str:
    return str(
        pendientes().compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _condiciones() -> str:
    """Sólo lo que va detrás de cada WHERE: las columnas del SELECT nombran
    `status` y `reviews_decision_id` sin que filtren por ellas."""
    trozos = _sql().split("WHERE")[1:]
    # Cada trozo acaba donde empieza otra cláusula: tras el WHERE del CTE
    # viene el SELECT exterior con todas las columnas.
    return " ".join(t.split("ORDER BY")[0].split(" SELECT ")[0] for t in trozos)


def test_la_vigente_es_la_ultima_del_motor_por_ficha() -> None:
    vigente = _sql().split("dictaminada AS", 1)[0]
    assert "DISTINCT ON (intelligence.classification_decisions.product_dna_id)" in vigente
    assert "created_at DESC" in vigente
    # Un veredicto no es la decisión vigente: si contara, el veredicto sobre una
    # decisión vieja escondería la nueva.
    assert "data_origin != 'HUMAN_VALIDATED'" in vigente


def test_el_dictamen_es_de_la_ficha_no_de_la_decision() -> None:
    """Buscarlo por `reviews_decision_id` dejaba en la bandeja los 33 casos
    que César ya había dictaminado antes de reclasificar el corpus."""
    dictaminada = _sql().split("dictaminada AS", 1)[1].split(")", 1)[0]
    assert "data_origin = 'HUMAN_VALIDATED'" in dictaminada
    assert "reviews_decision_id" not in _condiciones()
    assert "NOT (EXISTS" in _condiciones()


def test_pendiente_es_la_bandera_no_el_status() -> None:
    """`status` deja fuera las INSUFFICIENT_INFORMATION y las RGI 3 c)
    resueltas pero marcadas."""
    assert "requires_human_review IS true" in _condiciones()
    assert ".status" not in _condiciones()


def test_las_decisiones_sin_ficha_no_se_pierden() -> None:
    assert "sin_ficha.product_dna_id IS NULL" in _sql()


def test_la_definicion_no_trae_pagina() -> None:
    """Una página es de quien la pinta. Contar sobre ella diría 14 donde son 20."""
    assert "LIMIT" not in _sql().upper()


# ── Las preguntas, tal cual las dejó el motor ───────────────────────────────


def _caso(*preguntas: dict[str, Any], product_id: uuid.UUID | None = None) -> Any:
    d = ClassificationDecision(
        product_id=product_id or uuid.uuid4(),
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="HUMAN_REVIEW_REQUIRED",
        engine_version="0.1.0",
        requires_human_review=True,
        data_origin="SYNTHETIC",
    )
    d.id = uuid.uuid4()
    d.rgi_trace = [
        {"rule_id": "RGI-1", "preguntas": [{"codigo": "7304", "exige": "no cuenta"}]},
        {"rule_id": "RGI-6", "preguntas": list(preguntas)},
    ]
    return d


def _q(codigo: str, exige: str) -> dict[str, str]:
    return {"codigo": codigo, "exige": exige, "mercancia": "construccion = «6x36»"}


def test_se_leen_del_ultimo_paso() -> None:
    assert [q["exige"] for q in preguntas_de(_caso(_q("73121008", CLAUSULA)))] == [CLAUSULA]


def test_una_traza_rara_no_rompe_nada() -> None:
    caso = _caso()
    caso.rgi_trace = [None]
    assert preguntas_de(caso) == []
    caso.rgi_trace = [{"preguntas": [{"codigo": "73121008"}, "basura"]}]
    assert preguntas_de(caso) == [], "una pregunta sin cláusula no se puede contestar"
    caso.rgi_trace = None
    assert preguntas_de(caso) == []


class _Sesion:
    def __init__(self, casos: list[Any]) -> None:
        self._casos = casos
        self.sql: list[str] = []

    def scalars(self, sentencia: Any) -> Any:
        self.sql.append(str(sentencia))
        r = type("R", (), {})()
        r.all = lambda: list(self._casos)
        return r


def test_el_recalculo_usa_la_misma_definicion() -> None:
    """Antes cogía TODAS las pendientes, no la vigente de cada caso."""
    sesion = _Sesion([_caso(_q("73121008", CLAUSULA))])
    productos_que_preguntaban(sesion, CLAUSULA)  # type: ignore[arg-type]
    assert sesion.sql == [str(pendientes())]


def test_el_recalculo_va_por_clausula_no_por_posicion() -> None:
    uno, otro = uuid.uuid4(), uuid.uuid4()
    sesion = _Sesion(
        [
            _caso(_q("73121008", CLAUSULA), product_id=uno),
            _caso(_q("73121009", CLAUSULA), product_id=otro),
        ]
    )
    assert productos_que_preguntaban(sesion, CLAUSULA) == [uno, otro]  # type: ignore[arg-type]


def test_sin_producto_no_hay_nada_que_recalcular() -> None:
    caso = _caso(_q("73121008", CLAUSULA))
    caso.product_id = None
    assert productos_que_preguntaban(_Sesion([caso]), CLAUSULA) == []  # type: ignore[arg-type]
