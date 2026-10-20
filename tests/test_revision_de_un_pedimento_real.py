"""La revisión de un pedimento real, de punta a punta, contra Postgres.

El 20-oct la revisión devolvía 500 en todos los pedimentos: `_skus_de`
construía un dict directamente de un `Result`, y `dict()` lo tomaba por un
mapping. Los tests del router usaban sesiones falsas sin productos ligados y no
pasaban por ahí. Éste sí: se ejecuta dentro de una transacción que se revierte.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from apps.api.routers.pedimentos import ReviewRequest, _skus_de, revisar
from database.models import Pedimento, PedimentoItem

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _un_pedimento_con_producto(session: Session) -> Pedimento | None:
    return session.scalars(
        sa.select(Pedimento)
        .join(PedimentoItem, PedimentoItem.pedimento_id == Pedimento.id)
        .where(PedimentoItem.product_id.isnot(None))
        .limit(1)
    ).first()


def test_los_skus_de_las_partidas(pg_session: Session) -> None:  # noqa: F811
    pedimento = _un_pedimento_con_producto(pg_session)
    if pedimento is None:
        pytest.skip("la base no tiene partidas con producto ligado")
    partidas = pg_session.scalars(
        sa.select(PedimentoItem).where(PedimentoItem.pedimento_id == pedimento.id)
    ).all()
    skus = _skus_de(pg_session, partidas)
    assert skus and all(isinstance(s, str) for s in skus.values())


def test_revisar_un_pedimento_real_no_revienta(pg_session: Session) -> None:  # noqa: F811
    pedimento = _un_pedimento_con_producto(pg_session)
    if pedimento is None:
        pytest.skip("la base no tiene partidas con producto ligado")
    respuesta = revisar(pedimento.id, ReviewRequest(iva_rate="0.16", dta_rate="0.008"), pg_session)
    assert respuesta.summary
