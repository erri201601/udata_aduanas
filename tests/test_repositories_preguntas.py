"""Una sola definición de «pendiente», y las preguntas agrupadas sobre ella.

Hasta el 6-oct la bandeja, el script de la terminal y el recálculo al contestar
tenían cada uno su conjunto de pendientes, y no coincidían: la tarjeta de una
pregunta podía decir 14 casos y el recálculo tocar otros.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationDecision, Product
from database.repositories.preguntas import (
    agrupar,
    pendientes_vigentes,
    preguntas_de,
    productos_que_preguntaban,
)
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
CLAUSULA = "constituidos por 7 alambres"


def _caso(
    *preguntas: dict[str, Any],
    product_id: uuid.UUID | None = None,
    origen: str = "SYNTHETIC",
) -> ClassificationDecision:
    d = ClassificationDecision(
        product_id=product_id or uuid.uuid4(),
        product_dna_id=uuid.uuid4(),
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="HUMAN_REVIEW_REQUIRED",
        fraction_code=None,
        engine_version="0.1.0",
        requires_human_review=True,
        data_origin=origen,
    )
    d.id = uuid.uuid4()
    d.created_at = AHORA
    d.rgi_trace = [
        {"rule_id": "RGI-1", "status": "CONTINUE", "preguntas": [_q("73049099", "no cuenta")]},
        {"rule_id": "RGI-6", "status": "HUMAN_REVIEW_REQUIRED", "preguntas": list(preguntas)},
    ]
    return d


def _q(codigo: str, exige: str, mercancia: str = "construccion = «6x36»") -> dict[str, Any]:
    return {
        "codigo": codigo,
        "exige": exige,
        "mercancia": mercancia,
        "texto": f"La posición {codigo} exige «{exige}». ¿La cumple?",
    }


class Sesion:
    """Devuelve los casos a la consulta de pendientes y los productos a la suya."""

    def __init__(self, casos: list[ClassificationDecision], productos: list[Product] = []) -> None:  # noqa: B006
        self._casos = casos
        self._productos = productos
        self.sql: list[str] = []

    def scalars(self, sentencia: Any) -> Any:
        sql = str(sentencia)
        self.sql.append(sql)
        r = type("R", (), {})()
        if "FROM operational.products" in sql:
            r.all = lambda: list(self._productos)
        else:
            r.all = lambda: list(self._casos)
        return r


# ── La definición ───────────────────────────────────────────────────────────


def test_pendiente_es_la_bandera_no_el_status() -> None:
    """`status = 'HUMAN_REVIEW_REQUIRED'` deja fuera las INSUFFICIENT_INFORMATION
    y las RGI 3 c) resueltas pero marcadas. La bandera es lo que significa «una
    persona tiene que mirarlo»."""
    where = str(pendientes_vigentes()).split("WHERE", 1)[1]
    assert "requires_human_review IS true" in where
    assert ".status" not in where


def test_pendiente_es_la_ultima_decision_de_cada_ficha() -> None:
    sql = str(pendientes_vigentes())
    assert "max(otra.created_at)" in sql
    assert "otra.product_dna_id = intelligence.classification_decisions.product_dna_id" in sql
    assert "product_dna_id IS NULL" in sql, "una decisión sin ficha se perdería"
    assert "data_origin !=" in sql


def test_la_definicion_no_trae_pagina() -> None:
    """50 es una página de la bandeja, no una definición: contar sobre ella
    haría decir 14 donde son 20."""
    assert "LIMIT" not in str(pendientes_vigentes()).upper()


# ── Las preguntas, tal cual las dejó el motor ───────────────────────────────


def test_se_leen_del_ultimo_paso_de_la_traza() -> None:
    caso = _caso(_q("73121008", CLAUSULA))
    assert [q["exige"] for q in preguntas_de(caso)] == [CLAUSULA]


def test_una_traza_rara_no_rompe_la_bandeja() -> None:
    caso = _caso()
    caso.rgi_trace = [None]
    assert preguntas_de(caso) == []
    caso.rgi_trace = [{"preguntas": [{"codigo": "73121008"}, "basura"]}]
    assert preguntas_de(caso) == [], "una pregunta sin cláusula no se puede contestar"
    caso.rgi_trace = None
    assert preguntas_de(caso) == []


def test_la_misma_clausula_en_veinte_casos_es_una_pregunta() -> None:
    grupos = agrupar([_caso(_q("73121008", CLAUSULA)) for _ in range(20)])
    assert len(grupos) == 1
    assert len(grupos[0].decisiones) == 20


def test_primero_la_que_mas_rinde() -> None:
    casos = [_caso(_q("84818099", "Artículos de grifería"))] + [
        _caso(_q("73121008", CLAUSULA)) for _ in range(3)
    ]
    grupos = agrupar(casos)
    assert [g.codigo for g in grupos] == ["73121008", "84818099"]


def test_a_igualdad_el_orden_no_baila() -> None:
    a = _caso(_q("73121008", CLAUSULA))
    b = _caso(_q("73049099", "Tubos y perfiles huecos"))
    assert [g.codigo for g in agrupar([a, b])] == [g.codigo for g in agrupar([b, a])]


def test_la_misma_clausula_en_otra_posicion_es_otra_tarjeta() -> None:
    grupos = agrupar([_caso(_q("73121008", CLAUSULA)), _caso(_q("73121009", CLAUSULA))])
    assert {g.codigo for g in grupos} == {"73121008", "73121009"}


def test_las_fichas_distintas_se_conservan_sin_repetir() -> None:
    """Si son varias, la respuesta puede no valer igual para todas, y quien
    contesta tiene que verlo."""
    grupos = agrupar(
        [
            _caso(_q("73121008", CLAUSULA, "construccion = «6x36»")),
            _caso(_q("73121008", CLAUSULA, "construccion = «6x36»")),
            _caso(_q("73121008", CLAUSULA, "construccion = «6x19»")),
        ]
    )
    assert grupos[0].fichas == ("construccion = «6x36»", "construccion = «6x19»")


def test_un_caso_no_cuenta_dos_veces_en_la_misma_pregunta() -> None:
    caso = _caso(_q("73121008", CLAUSULA), _q("73121008", CLAUSULA))
    assert len(agrupar([caso])[0].decisiones) == 1


# ── El recálculo cuenta sobre el mismo conjunto ─────────────────────────────


def test_el_recalculo_usa_la_misma_definicion_que_la_bandeja() -> None:
    """Antes cogía TODAS las pendientes, no la última de cada ficha: la
    tarjeta decía 14 y el recálculo hacía otra cosa."""
    sesion = Sesion([_caso(_q("73121008", CLAUSULA))])
    productos_que_preguntaban(sesion, CLAUSULA)  # type: ignore[arg-type]
    assert sesion.sql == [str(pendientes_vigentes())]


def test_el_recalculo_va_por_clausula_no_por_posicion() -> None:
    """La respuesta se guarda sin posición: es verdad en cualquier posición que
    diga esa frase."""
    uno, otro = uuid.uuid4(), uuid.uuid4()
    sesion = Sesion(
        [
            _caso(_q("73121008", CLAUSULA), product_id=uno),
            _caso(_q("73121009", CLAUSULA), product_id=otro),
        ]
    )
    assert productos_que_preguntaban(sesion, CLAUSULA) == [uno, otro]  # type: ignore[arg-type]


def test_sin_producto_no_hay_nada_que_recalcular() -> None:
    caso = _caso(_q("73121008", CLAUSULA))
    caso.product_id = None
    assert productos_que_preguntaban(Sesion([caso]), CLAUSULA) == []  # type: ignore[arg-type]


# ── El endpoint ─────────────────────────────────────────────────────────────


def _producto(product_id: uuid.UUID, sku: str) -> Product:
    p = Product(sku=sku, commercial_name=f"Cable {sku}", data_origin="SYNTHETIC")
    p.id = product_id
    return p


def _get(sesion: Sesion) -> Any:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion
    with TestClient(app) as c:
        return c.get("/review/preguntas")


def test_el_endpoint_agrupa_y_cuenta_el_conjunto_entero() -> None:
    ids = [uuid.uuid4() for _ in range(14)]
    casos = [_caso(_q("73121008", CLAUSULA), product_id=i) for i in ids]
    casos.append(_caso(_q("84818099", "Artículos de grifería")))
    sesion = Sesion(casos, [_producto(i, f"CAB-{n:02d}") for n, i in enumerate(ids)])

    r = _get(sesion)

    assert r.status_code == 200
    cuerpo = r.json()
    assert [(p["codigo"], len(p["casos"])) for p in cuerpo] == [
        ("73121008", 14),
        ("84818099", 1),
    ]
    primero = cuerpo[0]
    assert primero["exige"] == CLAUSULA
    assert primero["fichas"] == ["construccion = «6x36»"]
    assert primero["casos"][0]["sku"] == "CAB-00"
    assert primero["casos"][0]["mercancia"] == "construccion = «6x36»"


def test_cada_caso_dice_su_origen() -> None:
    """SYNTHETIC se marca en la UI caso por caso: el dato tiene que llegar."""
    r = _get(Sesion([_caso(_q("73121008", CLAUSULA), origen="SYNTHETIC")]))
    assert r.json()[0]["casos"][0]["data_origin"] == "SYNTHETIC"


def test_avisa_si_la_misma_clausula_esta_en_otra_posicion() -> None:
    """Contestar una tarjeta contesta la otra: la respuesta no lleva posición."""
    r = _get(Sesion([_caso(_q("73121008", CLAUSULA)), _caso(_q("73121009", CLAUSULA))]))
    por_codigo = {p["codigo"]: p["tambien_en"] for p in r.json()}
    assert por_codigo == {"73121008": ["73121009"], "73121009": ["73121008"]}


def test_los_productos_se_piden_en_una_sola_consulta() -> None:
    sesion = Sesion([_caso(_q("73121008", CLAUSULA)) for _ in range(5)])
    _get(sesion)
    assert sum("FROM operational.products" in s for s in sesion.sql) == 1


def test_sin_preguntas_la_lista_esta_vacia() -> None:
    r = _get(Sesion([_caso()]))
    assert r.status_code == 200
    assert r.json() == []
