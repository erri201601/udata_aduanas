"""Tests de integración de `database.repositories.invoices.divisa_de_la_factura`.

Extraído de `apps.api.routers.pedimentos` para que el Espejo
(`_tipo_de_cambio_esperado`) y la métrica (`apps.evaluacion.deteccion_26`)
lean la MISMA consulta — ver el docstring del módulo para el bug real
que esto corrigió (Erick, 7-oct)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models import Client, Invoice, InvoiceItem, PedimentoItem, Supplier
from database.repositories.invoices import divisa_de_la_factura
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration


@pytest.fixture
def pg_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Sesión contra el Postgres local. Salta el test si no hay conexión."""
    from apps.api.config import get_settings

    monkeypatch.setenv("ADUANERO_ENV_FILE", ".env")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    engine = sa.create_engine(get_settings().sqlalchemy_url)
    try:
        conn = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"sin PostgreSQL local: {exc}")
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()
        engine.dispose()


def test_devuelve_la_divisa_de_la_factura_no_la_de_la_partida(pg_session: Session) -> None:
    """El caso real: `price_paid_currency` es MXN, `Invoice.currency` es
    USD -- ésta función debe devolver USD."""
    cliente = Client(legal_name="Cliente de prueba", data_origin="SYNTHETIC")
    proveedor = Supplier(legal_name="Proveedor de prueba", country="CN", data_origin="SYNTHETIC")
    pg_session.add_all([cliente, proveedor])
    pg_session.flush()
    factura = Invoice(
        client_id=cliente.id,
        supplier_id=proveedor.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        invoice_date=date(2026, 8, 1),
        currency="USD",
        total_amount=Decimal("100.00"),
        total_amount_currency="USD",
        data_origin="SYNTHETIC",
    )
    pg_session.add(factura)
    pg_session.flush()
    partida_factura = InvoiceItem(
        invoice_id=factura.id,
        line_number=1,
        description="Prueba",
        quantity=Decimal("1"),
        unit_price=Decimal("100.00"),
        unit_price_currency="USD",
        line_total=Decimal("100.00"),
        line_total_currency="USD",
        data_origin="SYNTHETIC",
    )
    pg_session.add(partida_factura)
    pg_session.flush()

    partida = PedimentoItem(
        line_number=1,
        description="Prueba",
        quantity=Decimal("1"),
        data_origin="SYNTHETIC",
        invoice_item_id=partida_factura.id,
        product_id=None,
        price_paid_currency="MXN",
        customs_value_currency="MXN",
    )

    assert divisa_de_la_factura(pg_session, partida) == "USD"


def test_sin_factura_ligada_devuelve_none(pg_session: Session) -> None:
    partida = PedimentoItem(
        line_number=1,
        description="Prueba",
        quantity=Decimal("1"),
        data_origin="SYNTHETIC",
        invoice_item_id=None,
        product_id=None,
    )

    assert divisa_de_la_factura(pg_session, partida) is None
