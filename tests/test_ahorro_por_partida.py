"""El Panorama toma el mayor ahorro por partida, no la suma (ADR 0011).

PROSEC, Regla 8ª y un sobrepago sobre la misma partida son caminos distintos
al mismo IGI. Contra Postgres, en una transacción que se revierte: se compara
el ahorro antes y después de colgar dos alternativas de una partida nueva.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from apps.api.routers.dashboard import tablero
from database.models import (
    Client,
    OpportunityFinding,
    Pedimento,
    PedimentoItem,
    ShadowReview,
)

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

SINTETICO = {"data_origin": "SYNTHETIC"}


def _oportunidad(
    revision: ShadowReview, partida: PedimentoItem, tipo: str, monto: str
) -> OpportunityFinding:
    return OpportunityFinding(
        pedimento_id=revision.pedimento_id,
        shadow_review_id=revision.id,
        pedimento_item_id=partida.id,
        opportunity_type=tipo,
        status="POTENTIAL",
        estimated_saving_amount=Decimal(monto),
        estimated_saving_amount_currency="MXN",
        is_simulation=True,
        **SINTETICO,
    )


def test_dos_caminos_al_mismo_igi_cuentan_una_vez(pg_session: Session) -> None:  # noqa: F811
    antes = tablero(pg_session).oportunidades
    if antes.monedas_mezcladas or antes.ahorro_moneda not in (None, "MXN"):
        pytest.skip("la base tiene ahorros en otra divisa: la suma no es comparable")

    cliente = Client(legal_name="Prueba ahorro por partida", country="MX", **SINTETICO)
    pg_session.add(cliente)
    pg_session.flush()
    pedimento = Pedimento(
        client_id=cliente.id,
        pedimento_number=f"PRUEBA-{uuid.uuid4().hex[:12]}",
        trade_flow="IMPORT",
        operation_date=date(2026, 10, 13),
        is_simulation=True,
        **SINTETICO,
    )
    pg_session.add(pedimento)
    pg_session.flush()
    partida = PedimentoItem(
        pedimento_id=pedimento.id,
        line_number=1,
        description="prueba",
        quantity=Decimal(1),
        **SINTETICO,
    )
    revision = ShadowReview(pedimento_id=pedimento.id, is_complete=False, **SINTETICO)
    pg_session.add_all([partida, revision])
    pg_session.flush()
    pg_session.add_all(
        [
            _oportunidad(revision, partida, "PROSEC", "100"),
            _oportunidad(revision, partida, "REGLA_8A", "150"),
        ]
    )
    pg_session.flush()

    despues = tablero(pg_session).oportunidades
    assert (despues.ahorro_cuantificado or 0) - (antes.ahorro_cuantificado or 0) == Decimal(150)
