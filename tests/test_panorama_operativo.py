"""El Panorama operativo: en qué está cada pedimento y qué sigue.

Contra Postgres, en una transacción que se revierte. La base compartida ya
tiene pedimentos, así que los tests no cuentan totales: crean los suyos y
miran sólo esas filas.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from apps.api.routers.dashboard import _siguiente_accion, panorama_operativo
from database.models import Client, Pedimento, PedimentoItem, RiskFinding, ShadowReview

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from apps.api.routers.dashboard import Operacion
    from sqlalchemy.orm import Session

SINTETICO = {"data_origin": "SYNTHETIC"}


def _pedimento(session: Session, cliente: Client) -> Pedimento:
    p = Pedimento(
        client_id=cliente.id,
        pedimento_number=f"PRUEBA-{uuid.uuid4().hex[:12]}",
        trade_flow="IMPORT",
        operation_date=date(2026, 10, 13),
        is_simulation=True,
        **SINTETICO,
    )
    session.add(p)
    session.flush()
    return p


def _fila(session: Session, p: Pedimento) -> Operacion:
    return next(o for o in panorama_operativo(session).operaciones if o.pedimento_id == str(p.id))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("revisado", "completa", "criticos", "esperada"),
    [
        (False, None, 0, "Revisar pedimento"),
        (True, False, 2, "Revisar hallazgos críticos"),
        (True, True, 1, "Revisar hallazgos críticos"),
        (True, False, 0, "Completar revisión"),
        (True, True, 0, "Sin acción pendiente"),
    ],
)
def test_la_siguiente_accion_sale_del_estado(
    revisado: bool, completa: bool | None, criticos: int, esperada: str
) -> None:
    cuando = datetime(2026, 10, 21, tzinfo=UTC) if revisado else None
    assert _siguiente_accion(cuando, completa, criticos) == esperada


@pytest.mark.integration
def test_un_pedimento_sin_revisar_no_se_presenta_como_limpio(pg_session: Session) -> None:  # noqa: F811
    cliente = Client(legal_name="Prueba panorama", rfc="PPA010101AAA", country="MX", **SINTETICO)
    pg_session.add(cliente)
    pg_session.flush()
    p = _pedimento(pg_session, cliente)

    fila = _fila(pg_session, p)
    assert fila.revisado_en is None
    assert fila.revision_completa is None
    assert fila.hallazgos == 0
    assert fila.siguiente_accion == "Revisar pedimento"
    assert fila.cliente == "Prueba panorama"
    assert fila.rfc == "PPA010101AAA"
    assert fila.simulado is True


@pytest.mark.integration
def test_cuenta_solo_la_ultima_revision_y_sin_duplicar_lo_del_documento(
    pg_session: Session,  # noqa: F811
) -> None:
    cliente = Client(legal_name="Prueba panorama", country="MX", **SINTETICO)
    pg_session.add(cliente)
    pg_session.flush()
    p = _pedimento(pg_session, cliente)
    partidas = [
        PedimentoItem(
            pedimento_id=p.id, line_number=n, description="prueba", quantity=1, **SINTETICO
        )
        for n in (1, 2)
    ]
    # Fechas explícitas: dentro de una transacción `now()` es el mismo para
    # las dos y la vigente quedaría a la suerte.
    vieja = ShadowReview(
        pedimento_id=p.id,
        is_complete=True,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        **SINTETICO,
    )
    pg_session.add_all([*partidas, vieja])
    pg_session.flush()
    pg_session.add(
        RiskFinding(
            pedimento_id=p.id,
            shadow_review_id=vieja.id,
            finding_type="FRACCION_MISMATCH",
            severity="HIGH",
            **SINTETICO,
        )
    )
    pg_session.flush()
    nueva = ShadowReview(
        pedimento_id=p.id,
        is_complete=False,
        created_at=datetime(2026, 10, 2, tzinfo=UTC),
        **SINTETICO,
    )
    pg_session.add(nueva)
    pg_session.flush()
    # El tipo de cambio es dato del documento: sale igual en las dos partidas
    # y cuenta una vez.
    pg_session.add_all(
        RiskFinding(
            pedimento_id=p.id,
            pedimento_item_id=partida.id,
            shadow_review_id=nueva.id,
            finding_type="EXCHANGE_RATE_MISMATCH",
            field="exchange_rate",
            declared_value="18.0",
            expected_value="18.5",
            severity="CRITICAL",
            **SINTETICO,
        )
        for partida in partidas
    )
    pg_session.flush()

    fila = _fila(pg_session, p)
    assert fila.revision_completa is False
    assert fila.hallazgos == 1
    assert fila.criticos == 1
    assert fila.peor_severidad == "CRITICAL"
    assert fila.siguiente_accion == "Revisar hallazgos críticos"

    atencion = {a.clave: a for a in panorama_operativo(pg_session).atencion}
    assert atencion["criticos"].tono == "mal"
    assert atencion["criticos"].pantalla == "finding-detail"
