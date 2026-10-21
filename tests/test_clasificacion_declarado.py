"""El expediente de clasificación trae lo declarado, aparte de lo sugerido.

Contra Postgres, en una transacción que se revierte.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from apps.api.routers.classifications import obtener_decision
from database.models import (
    ClassificationDecision,
    Client,
    Pedimento,
    PedimentoItem,
    Product,
)

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada
from tests.test_pendientes_integracion import _ficha, _motor, _veredicto

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

SINTETICO = {"data_origin": "SYNTHETIC"}


def _decision(session: Session, producto: Product | None) -> ClassificationDecision:
    d = ClassificationDecision(
        product_id=producto.id if producto else None,
        trade_flow="IMPORT",
        operation_date=date(2026, 10, 13),
        status="RESOLVED",
        fraction_code="73121005",
        requires_human_review=False,
        **SINTETICO,
    )
    session.add(d)
    session.flush()
    return d


def test_lo_declarado_no_se_confunde_con_lo_sugerido(pg_session: Session) -> None:  # noqa: F811
    cliente = Client(legal_name="Prueba declarado", country="MX", **SINTETICO)
    pg_session.add(cliente)
    pg_session.flush()
    producto = Product(
        client_id=cliente.id,
        sku=f"PRUEBA-{uuid.uuid4().hex[:8]}",
        commercial_name="Cable de acero de prueba",
        **SINTETICO,
    )
    pedimento = Pedimento(
        client_id=cliente.id,
        pedimento_number=f"PRUEBA-{uuid.uuid4().hex[:12]}",
        trade_flow="IMPORT",
        operation_date=date(2026, 10, 13),
        is_simulation=True,
        **SINTETICO,
    )
    pg_session.add_all([producto, pedimento])
    pg_session.flush()
    pg_session.add(
        PedimentoItem(
            pedimento_id=pedimento.id,
            product_id=producto.id,
            line_number=4,
            description="cable",
            quantity=Decimal(1),
            declared_fraction_code="73121099",
            declared_nico_code="06",
            **SINTETICO,
        )
    )
    pg_session.flush()

    detalle = obtener_decision(_decision(pg_session, producto).id, pg_session)

    assert detalle.producto == "Cable de acero de prueba"
    assert detalle.fraction_code == "73121005"
    assert [
        (d.pedimento_number, d.line_number, d.fraction_code, d.nico_code) for d in detalle.declarado
    ] == [(pedimento.pedimento_number, 4, "73121099", "06")]
    assert detalle.dictamen is None


def test_sin_producto_no_hay_declarado(pg_session: Session) -> None:  # noqa: F811
    detalle = obtener_decision(_decision(pg_session, None).id, pg_session)
    assert detalle.declarado == []
    assert detalle.producto is None


def test_tras_reclasificar_el_caso_sigue_confirmado(pg_session: Session) -> None:  # noqa: F811
    """La vigente no hereda el veredicto, pero la cabecera no puede decir «pendiente»."""
    ficha = _ficha(pg_session)
    revisada = _motor(pg_session, ficha, 0, pendiente=False)
    _veredicto(pg_session, revisada, 1)
    vigente = _motor(pg_session, ficha, 2, pendiente=False)

    detalle = obtener_decision(vigente.id, pg_session)

    assert detalle.dictamen is None
    assert detalle.dictamen_del_caso is not None
    assert detalle.dictamen_del_caso.fraction_code == "73121005"
