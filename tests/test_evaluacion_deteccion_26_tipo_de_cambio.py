"""Tests de integración de
`apps.evaluacion.deteccion_26._tipos_de_cambio_ciertos`: las partidas con
un tipo de cambio declarado que no es el FIX oficial no deben contar como
falsos positivos -- mismo criterio que `_cuotas_compensatorias_ciertas`,
corregido junto con el bug de `_tipo_de_cambio_esperado` que impedía
verlas (Erick, 7-oct: medido contra la base compartida, 15 pedimentos con
diferencias de 5.8% a 11.9%).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models import Client, Invoice, InvoiceItem, Pedimento, PedimentoItem, Supplier
from database.models.regulatory import ExchangeRate
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "6" * 64
DIVISA = "YZX"


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


def _sembrar_fix(session: Session, *, dia: date, tasa: str) -> None:
    session.add(
        ExchangeRate(
            currency=DIVISA,
            rate=Decimal(tasa),
            data_origin="OFFICIAL",
            valid_from=dia,
            valid_to=dia,
            source_url="https://ejemplo.invalido/prueba",
            content_hash=HASH,
            retrieved_at=datetime.now(UTC),
        )
    )
    session.flush()


def _pedimento_con_partida(
    session: Session, *, exchange_rate: str, factura_currency: str = DIVISA
) -> tuple[uuid.UUID, PedimentoItem]:
    cliente = Client(legal_name="Cliente de prueba", data_origin="SYNTHETIC")
    proveedor = Supplier(legal_name="Proveedor de prueba", country="CN", data_origin="SYNTHETIC")
    session.add_all([cliente, proveedor])
    session.flush()

    factura = Invoice(
        client_id=cliente.id,
        supplier_id=proveedor.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        invoice_date=date(2026, 8, 3),
        currency=factura_currency,
        total_amount=Decimal("100.00"),
        total_amount_currency=factura_currency,
        data_origin="SYNTHETIC",
    )
    session.add(factura)
    session.flush()
    partida_factura = InvoiceItem(
        invoice_id=factura.id,
        line_number=1,
        description="Prueba",
        quantity=Decimal("1"),
        unit_price=Decimal("100.00"),
        unit_price_currency=factura_currency,
        line_total=Decimal("100.00"),
        line_total_currency=factura_currency,
        data_origin="SYNTHETIC",
    )
    session.add(partida_factura)
    session.flush()

    pedimento = Pedimento(
        client_id=cliente.id,
        pedimento_number=f"26{uuid.uuid4().int % 10**19:019d}"[:21],
        trade_flow="IMPORT",
        operation_date=date(2026, 8, 3),
        currency="MXN",
        exchange_rate=Decimal(exchange_rate),
        data_origin="SYNTHETIC",
    )
    session.add(pedimento)
    session.flush()

    partida = PedimentoItem(
        pedimento_id=pedimento.id,
        line_number=1,
        description="Prueba",
        quantity=Decimal("1"),
        data_origin="SYNTHETIC",
        invoice_item_id=partida_factura.id,
        product_id=None,
        price_paid_currency="MXN",
        customs_value_currency="MXN",
    )
    session.add(partida)
    session.flush()
    return pedimento.id, partida


def test_un_tipo_de_cambio_distinto_del_fix_no_cuenta_como_falso_positivo(
    pg_session: Session,
) -> None:
    from apps.evaluacion.deteccion_26 import DETECTOR_DE_TIPO_DE_CAMBIO, _tipos_de_cambio_ciertos

    _sembrar_fix(pg_session, dia=date(2026, 8, 3), tasa="17.000000")
    pedimento_id, partida = _pedimento_con_partida(pg_session, exchange_rate="18.500000")

    ciertos = _tipos_de_cambio_ciertos(
        pg_session,
        {partida.id: partida},
        {pedimento_id: date(2026, 8, 3)},
        {pedimento_id: Decimal("18.500000")},
    )

    assert ciertos == {(str(partida.id), DETECTOR_DE_TIPO_DE_CAMBIO)}


def test_un_tipo_de_cambio_dentro_de_tolerancia_no_cuenta(pg_session: Session) -> None:
    """Por debajo del 1% es ruido de redondeo -- mismo criterio que el
    comparador real (`core.shadow.compare.VALUE_TOLERANCE`)."""
    from apps.evaluacion.deteccion_26 import _tipos_de_cambio_ciertos

    _sembrar_fix(pg_session, dia=date(2026, 8, 3), tasa="17.000000")
    pedimento_id, partida = _pedimento_con_partida(pg_session, exchange_rate="17.050000")

    ciertos = _tipos_de_cambio_ciertos(
        pg_session,
        {partida.id: partida},
        {pedimento_id: date(2026, 8, 3)},
        {pedimento_id: Decimal("17.050000")},
    )

    assert ciertos == set()


def test_sin_fix_cargado_no_se_afirma_nada(pg_session: Session) -> None:
    from apps.evaluacion.deteccion_26 import _tipos_de_cambio_ciertos

    pedimento_id, partida = _pedimento_con_partida(pg_session, exchange_rate="18.500000")

    ciertos = _tipos_de_cambio_ciertos(
        pg_session,
        {partida.id: partida},
        {pedimento_id: date(2026, 8, 3)},
        {pedimento_id: Decimal("18.500000")},
    )

    assert ciertos == set()


def test_factura_en_mxn_no_tiene_nada_que_comparar(pg_session: Session) -> None:
    from apps.evaluacion.deteccion_26 import _tipos_de_cambio_ciertos

    pedimento_id, partida = _pedimento_con_partida(
        pg_session, exchange_rate="18.500000", factura_currency="MXN"
    )

    ciertos = _tipos_de_cambio_ciertos(
        pg_session,
        {partida.id: partida},
        {pedimento_id: date(2026, 8, 3)},
        {pedimento_id: Decimal("18.500000")},
    )

    assert ciertos == set()
