"""El dictamen sobre una mercancía vale para la misma mercancía en otra ficha.

El generador sintético crea productos nuevos con la misma descripción que una
ficha ya dictaminada: el cable 6x36 sin recubrimiento que César dictaminó
73121005. Sin esto, un pedimento limpio generado que declara 73121099 sumaba
un falso positivo por un hallazgo cierto (20-oct). Contra Postgres, en una
transacción que se revierte.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from apps.evaluacion.deteccion_26 import (
    DETECTOR_DE_FRACCION,
    _fracciones_que_un_dictamen_contradice,
)
from database.models import PedimentoItem, Product

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada
from tests.test_pendientes_integracion import _ficha, _motor, _veredicto

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _producto(session: Session, descripcion: str) -> Product:
    p = Product(
        sku=f"T-{uuid.uuid4().hex[:10]}",
        commercial_name="cable",
        description=descripcion,
        data_origin="SYNTHETIC",
    )
    session.add(p)
    session.flush()
    return p


def _dictaminado(session: Session, descripcion: str, *, falta: bool = False) -> None:
    ficha = _ficha(session, product=_producto(session, descripcion))
    ficha.is_current = True
    _veredicto(session, _motor(session, ficha, 1), 2, falta_informacion=falta)


def _partida_de(session: Session, descripcion: str) -> tuple[uuid.UUID, PedimentoItem]:
    ficha = _ficha(session, product=_producto(session, descripcion))
    ficha.is_current = True
    session.flush()
    return uuid.uuid4(), PedimentoItem(
        product_id=ficha.product_id, declared_fraction_code="73121099"
    )


def test_el_dictamen_de_la_misma_descripcion_vale(pg_session: Session) -> None:  # noqa: F811
    descripcion = f"CABLE 6X36 SIN RECUBRIMIENTO {uuid.uuid4().hex}"
    _dictaminado(pg_session, descripcion)
    pid, partida = _partida_de(pg_session, descripcion)

    contradichas = _fracciones_que_un_dictamen_contradice(pg_session, {pid: partida}, set())
    assert (str(pid), DETECTOR_DE_FRACCION) in contradichas


def test_si_los_dictamenes_de_esa_descripcion_no_coinciden_no_vale(pg_session: Session) -> None:  # noqa: F811
    descripcion = f"CABLE 6X36 SIN RECUBRIMIENTO {uuid.uuid4().hex}"
    _dictaminado(pg_session, descripcion)
    _dictaminado(pg_session, descripcion, falta=True)
    pid, partida = _partida_de(pg_session, descripcion)

    assert _fracciones_que_un_dictamen_contradice(pg_session, {pid: partida}, set()) == set()
