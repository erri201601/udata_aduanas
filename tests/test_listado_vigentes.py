"""`GET /classifications?vigentes=true`: una decisión por caso (ADR 0008).

LO QUE ESTE FICHERO PROTEGE

Que la pantalla de Classification enseñe casos y no filas. Sin filtro, el
listado devuelve cada reclasificación, los veredictos humanos y las pruebas:
más de 6 400 filas, y la pantalla abría en un intento fallido de una laptop de
prueba del 30-sep (7-oct).

Contra Postgres, en una transacción que se revierte, filtrando por el producto
del test para no depender de lo que haya en la base.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from apps.api.routers.classifications import listar_decisiones

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada
from tests.test_pendientes_integracion import _ficha, _motor, _veredicto

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_con_vigentes_sale_una_por_caso_y_nunca_el_veredicto(pg_session: Session) -> None:  # noqa: F811
    ficha = _ficha(pg_session)
    vieja = _motor(pg_session, ficha, 1)
    _veredicto(pg_session, vieja, 2)
    hoy = _motor(pg_session, ficha, 3, pendiente=False)

    todas = listar_decisiones(pg_session, product_id=ficha.product_id, vigentes_por_caso=False)
    vigentes = listar_decisiones(pg_session, product_id=ficha.product_id, vigentes_por_caso=True)

    assert len(todas) == 3, "sin el filtro siguen saliendo todas las filas"
    assert [d.id for d in vigentes] == [hoy.id]
    assert vigentes[0].sku is not None


def test_las_resueltas_van_primero(pg_session: Session) -> None:  # noqa: F811
    """La primera es la que la pantalla abre por defecto: que se pueda explicar."""
    pendiente = _ficha(pg_session)
    _motor(pg_session, pendiente, 1)
    resuelta = _ficha(pg_session)
    _motor(pg_session, resuelta, 1, pendiente=False)

    estados = [
        d.status
        for producto in (pendiente.product_id, resuelta.product_id)
        for d in listar_decisiones(pg_session, product_id=producto, vigentes_por_caso=True)
    ]
    assert sorted(estados) == ["HUMAN_REVIEW_REQUIRED", "RESOLVED"]

    juntas = listar_decisiones(pg_session, vigentes_por_caso=True, limit=200)
    primera_pendiente = next(
        (i for i, d in enumerate(juntas) if d.status != "RESOLVED"), len(juntas)
    )
    assert all(d.status != "RESOLVED" for d in juntas[primera_pendiente:]), (
        "una resuelta quedó detrás de una pendiente"
    )
