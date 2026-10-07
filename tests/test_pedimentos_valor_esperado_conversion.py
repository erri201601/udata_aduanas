"""Tests de integración de `apps.api.routers.pedimentos._valor_esperado`
convirtiendo a MXN con el FIX real (`ingestion.banxico`, 2026-10-06).

Antes de esto, una factura en una divisa distinta de MXN SIEMPRE devolvía
su propia divisa sin convertir, y `core/shadow/compare.py` reportaba
"divisa distinta" en cada partida real del corpus (invoices 100% USD,
pedimentos 100% MXN) — nunca llegaba a comparar el monto.

Usa `currency="ZZ"` (no choca con las filas USD reales ya cargadas en esta
base) para poder sembrar un tipo de cambio exacto y medible.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models import Client, Invoice, InvoiceItem, PedimentoItem, Supplier
from database.models.regulatory import ExchangeRate
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "e" * 64
DIVISA = "ZZZ"


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


def _partida(**kw: object) -> PedimentoItem:
    campos: dict[str, object] = {
        "line_number": 1,
        "description": "Tubo de acero",
        "declared_fraction_code": "73051291",
        "quantity": Decimal("10"),
        "country_of_origin": "BR",
        "data_origin": "SYNTHETIC",
        "invoice_item_id": uuid.uuid4(),
        "product_id": None,
    }
    campos.update(kw)
    return PedimentoItem(**campos)  # type: ignore[arg-type]


def _sembrar_tasa(session: Session, *, dia: date, tasa: str) -> None:
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


def test_convierte_a_mxn_con_la_tasa_vigente(pg_session: Session) -> None:
    from apps.api.routers.pedimentos import _valor_esperado

    _sembrar_tasa(pg_session, dia=date(2099, 5, 1), tasa="20.000000")
    partida = _partida(
        price_paid=Decimal("1000.00"),
        incrementables=Decimal("50.00"),
        price_paid_currency=DIVISA,
        incrementables_currency=DIVISA,
    )

    valor, moneda = _valor_esperado(pg_session, partida, date(2099, 5, 1))

    assert moneda == "MXN"
    assert valor == Decimal("21000.000000")  # (1000 + 50) * 20


def test_sin_tasa_cargada_para_esa_fecha_es_needs_validation(pg_session: Session) -> None:
    """Divisa/fecha sin ningún tipo de cambio sembrado -- no se inventa uno
    ni se compara sin convertir: `None`, la respuesta honesta."""
    from apps.api.routers.pedimentos import _valor_esperado

    partida = _partida(
        price_paid=Decimal("1000.00"),
        incrementables=Decimal("50.00"),
        price_paid_currency="YY",
        incrementables_currency="YY",
    )

    valor, moneda = _valor_esperado(pg_session, partida, date(1999, 1, 1))

    assert valor is None
    assert moneda is None


def test_no_se_confunde_con_la_divisa_de_la_factura(pg_session: Session) -> None:
    """Investigado a propósito (Erick, 7-oct) y NO es el mismo bug que
    `_tipo_de_cambio_esperado`: `price_paid`/`incrementables` son montos ya
    en MXN en esta misma fila (Art. 65 Ley Aduanera) -- aunque la factura
    ligada esté en otra divisa, esta función no debe tocarla ni mezclarla
    con su propia suma. Si alguna vez se "unifica" con
    `_divisa_de_la_factura`, este test debe seguir pasando."""
    from apps.api.routers.pedimentos import _valor_esperado

    cliente = Client(legal_name="Cliente de prueba", data_origin="SYNTHETIC")
    proveedor = Supplier(legal_name="Proveedor de prueba", country="BR", data_origin="SYNTHETIC")
    pg_session.add_all([cliente, proveedor])
    pg_session.flush()
    factura = Invoice(
        client_id=cliente.id,
        supplier_id=proveedor.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        invoice_date=date(2099, 5, 1),
        currency="USD",
        total_amount=Decimal("57.00"),
        total_amount_currency="USD",
        data_origin="SYNTHETIC",
    )
    pg_session.add(factura)
    pg_session.flush()
    partida_factura = InvoiceItem(
        invoice_id=factura.id,
        line_number=1,
        description="Tubo de acero",
        quantity=Decimal("10"),
        unit_price=Decimal("5.70"),
        unit_price_currency="USD",
        line_total=Decimal("57.00"),
        line_total_currency="USD",
        data_origin="SYNTHETIC",
    )
    pg_session.add(partida_factura)
    pg_session.flush()

    partida = _partida(
        price_paid=Decimal("1000.00"),
        incrementables=Decimal("50.00"),
        price_paid_currency="MXN",
        incrementables_currency="MXN",
        invoice_item_id=partida_factura.id,
    )

    valor, moneda = _valor_esperado(pg_session, partida, date(2099, 5, 1))

    # La suma propia de la partida, sin ningún FIX de por medio -- NO
    # 57.00 * algo, que sería mezclar la factura con esta cuenta.
    assert moneda == "MXN"
    assert valor == Decimal("1050.00")
