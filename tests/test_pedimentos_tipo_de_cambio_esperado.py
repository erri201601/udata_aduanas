"""Tests de integración de `apps.api.routers.pedimentos._tipo_de_cambio_esperado`
— consumidor del FIX que faltaba (Erick, 6-oct): el Espejo ya convertía el
valor de la factura con el FIX, pero nadie comparaba
`pedimentos.exchange_rate` (lo DECLARADO) contra el FIX real de la fecha de
operación. `regulatory.exchange_rates` tenía 192 filas (PR #199) y ningún
módulo de `apps/` o `core/` las consultaba para esto.

BUG REAL CORREGIDO (Erick, 7-oct), encontrado al medir contra la base
COMPARTIDA: la primera versión tomaba `partida.price_paid_currency` —
pero esa es la divisa en la que la PARTIDA imprime su propio precio
pagado (siempre MXN, Ley Aduanera), no la de la factura. Devolvía `None`
en el 100% de las 181 partidas reales, y el "0 FP" se leía como "coincide"
cuando en realidad nunca se había comparado nada. La divisa correcta sale
de `Invoice.currency` vía `partida → invoice_item → invoice`
(`_divisa_de_la_factura`) — estos tests ahora construyen una factura real
para probarlo, no sólo ponen el campo suelto en la partida.

Usa `currency="YZZ"` (no choca con las filas USD reales ya cargadas en esta
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

HASH = "f" * 64
DIVISA = "YZZ"


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


def _partida_con_factura(session: Session, *, factura_currency: str, **kw: object) -> PedimentoItem:
    """Partida con una factura REAL ligada, en `factura_currency` — no basta
    con poner `price_paid_currency` suelto: ese campo ya no decide nada
    aquí (ver docstring del módulo)."""
    cliente = Client(legal_name="Cliente de prueba", data_origin="SYNTHETIC")
    proveedor = Supplier(legal_name="Proveedor de prueba", country="CN", data_origin="SYNTHETIC")
    session.add_all([cliente, proveedor])
    session.flush()

    factura = Invoice(
        client_id=cliente.id,
        supplier_id=proveedor.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        invoice_date=date(2099, 6, 1),
        currency=factura_currency,
        total_amount=Decimal("1000.00"),
        total_amount_currency=factura_currency,
        data_origin="SYNTHETIC",
    )
    session.add(factura)
    session.flush()

    partida_factura = InvoiceItem(
        invoice_id=factura.id,
        line_number=1,
        description="Cable de acero",
        quantity=Decimal("10"),
        unit_price=Decimal("100.00"),
        unit_price_currency=factura_currency,
        line_total=Decimal("1000.00"),
        line_total_currency=factura_currency,
        data_origin="SYNTHETIC",
    )
    session.add(partida_factura)
    session.flush()

    campos: dict[str, object] = {
        "line_number": 1,
        "description": "Cable de acero",
        "declared_fraction_code": "73121099",
        "quantity": Decimal("10"),
        "country_of_origin": "CN",
        "data_origin": "SYNTHETIC",
        "invoice_item_id": partida_factura.id,
        "product_id": None,
        # El valor REAL de este bug: declarado en MXN siempre, sin importar
        # la divisa de la factura (Ley Aduanera).
        "price_paid_currency": "MXN",
        "customs_value_currency": "MXN",
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


def test_devuelve_el_fix_vigente_cuando_la_factura_es_otra_divisa(pg_session: Session) -> None:
    from apps.api.routers.pedimentos import _tipo_de_cambio_esperado

    _sembrar_tasa(pg_session, dia=date(2099, 6, 1), tasa="18.500000")
    partida = _partida_con_factura(pg_session, factura_currency=DIVISA)

    tasa = _tipo_de_cambio_esperado(pg_session, partida, date(2099, 6, 1))

    assert tasa == Decimal("18.500000")


def test_price_paid_currency_mxn_no_impide_detectar_la_divisa_de_la_factura(
    pg_session: Session,
) -> None:
    """El caso real del corpus: `price_paid_currency` es MXN (correcto,
    Ley Aduanera) pero la factura SÍ está en otra divisa -- antes de la
    corrección esto devolvía `None` siempre."""
    from apps.api.routers.pedimentos import _tipo_de_cambio_esperado

    _sembrar_tasa(pg_session, dia=date(2099, 6, 1), tasa="18.500000")
    partida = _partida_con_factura(pg_session, factura_currency=DIVISA, price_paid_currency="MXN")

    tasa = _tipo_de_cambio_esperado(pg_session, partida, date(2099, 6, 1))

    assert tasa == Decimal("18.500000")


def test_no_aplica_cuando_la_factura_ya_es_mxn(pg_session: Session) -> None:
    """Nada que convertir: `None` es «no aplica», no «coincide»."""
    from apps.api.routers.pedimentos import _tipo_de_cambio_esperado

    partida = _partida_con_factura(pg_session, factura_currency="MXN")

    tasa = _tipo_de_cambio_esperado(pg_session, partida, date(2099, 6, 1))

    assert tasa is None


def test_sin_tasa_cargada_para_esa_fecha_es_needs_validation(pg_session: Session) -> None:
    """Divisa/fecha sin ningún tipo de cambio sembrado -- no se inventa uno:
    `None`, la respuesta honesta (no se compara, no se afirma que coincida)."""
    from apps.api.routers.pedimentos import _tipo_de_cambio_esperado

    partida = _partida_con_factura(pg_session, factura_currency="XYW")

    tasa = _tipo_de_cambio_esperado(pg_session, partida, date(1999, 1, 1))

    assert tasa is None


def test_sin_factura_ligada_no_se_compara(pg_session: Session) -> None:
    from apps.api.routers.pedimentos import _tipo_de_cambio_esperado

    partida = PedimentoItem(
        line_number=1,
        description="Cable de acero",
        declared_fraction_code="73121099",
        quantity=Decimal("10"),
        country_of_origin="CN",
        data_origin="SYNTHETIC",
        invoice_item_id=None,
        product_id=None,
    )

    tasa = _tipo_de_cambio_esperado(pg_session, partida, date(2099, 6, 1))

    assert tasa is None
