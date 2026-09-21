"""Esquema `operational` — clientes, proveedores, productos y operaciones.

Hoy todo aquí es `SYNTHETIC` (§10 maestro): no hay acceso a datos reales de AJR.
Cada fila lleva `synthetic_scenario_id` + `seed` para ser reproducible, y jamás
se presenta como real en la UI.

El dinero es `NUMERIC(18,6)` con columna hermana `<campo>_currency CHAR(3)`.
Nunca `FLOAT`; en Python, `Decimal` (§22 maestro).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base
from database.models.enums import TRADE_FLOW
from database.models.mixins import (
    DataOriginMixin,
    SyntheticMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    check_enum,
)

_SCHEMA = "operational"
_MONEY = sa.Numeric(18, 6)
_CCY = sa.CHAR(3)


class SyntheticScenario(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, Base):
    """Registro de un escenario del generador sintético (§24 maestro).

    Es el ancla de reproducibilidad: `synthetic_scenario_id` de todo el esquema
    apunta aquí. No hereda `SyntheticMixin` — sería una autorreferencia.
    """

    __tablename__ = "synthetic_scenarios"
    __table_args__ = ({"schema": _SCHEMA},)

    slug: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    seed: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    generator_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class Client(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Importador/exportador. Hoy sintético."""

    __tablename__ = "clients"
    __table_args__ = ({"schema": _SCHEMA},)

    legal_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    rfc: Mapped[str | None] = mapped_column(sa.String(13), nullable=True)
    country: Mapped[str] = mapped_column(sa.String(2), nullable=False, server_default="MX")
    industry: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Proveedor extranjero o nacional del cliente."""

    __tablename__ = "suppliers"
    __table_args__ = ({"schema": _SCHEMA},)

    legal_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tax_id: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    country: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    manufacturer_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_manufacturer: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Product(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Mercancía en el catálogo del cliente. El Product DNA vive en `intelligence`."""

    __tablename__ = "products"
    __table_args__ = (
        sa.UniqueConstraint("client_id", "sku", name="uq_products_client_id_sku"),
        {"schema": _SCHEMA},
    )

    client_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.clients.id", ondelete="CASCADE"), nullable=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.suppliers.id", ondelete="SET NULL"), nullable=True
    )
    sku: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    commercial_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    model: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    manufacturer_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    country_of_manufacture: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Factura comercial de una operación."""

    __tablename__ = "invoices"
    __table_args__ = (
        sa.UniqueConstraint(
            "supplier_id", "invoice_number", name="uq_invoices_supplier_id_invoice_number"
        ),
        {"schema": _SCHEMA},
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.clients.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    invoice_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    incoterm: Mapped[str | None] = mapped_column(sa.String(3), nullable=True)
    currency: Mapped[str] = mapped_column(_CCY, nullable=False)
    subtotal_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    subtotal_amount_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    freight_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    freight_amount_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    insurance_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    insurance_amount_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    total_amount_currency: Mapped[str] = mapped_column(_CCY, nullable=False)


class InvoiceItem(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Partida de una factura."""

    __tablename__ = "invoice_items"
    __table_args__ = (
        sa.UniqueConstraint(
            "invoice_id", "line_number", name="uq_invoice_items_invoice_id_line_number"
        ),
        {"schema": _SCHEMA},
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.invoices.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.products.id", ondelete="SET NULL"), nullable=True
    )
    line_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    unit_of_measure: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    unit_price_currency: Mapped[str] = mapped_column(_CCY, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    line_total_currency: Mapped[str] = mapped_column(_CCY, nullable=False)


class Cove(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Comprobante de Valor Electrónico asociado a una factura."""

    __tablename__ = "coves"
    __table_args__ = ({"schema": _SCHEMA},)

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.invoices.id", ondelete="CASCADE"), nullable=False
    )
    cove_number: Mapped[str] = mapped_column(sa.String(32), nullable=False, unique=True)
    cove_type: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    issued_at: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    edocument_hash: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class Pedimento(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Pedimento declarado. El "espejo" esperado lo construye Pedimento Shadow."""

    __tablename__ = "pedimentos"
    __table_args__ = (
        sa.Index("ix_pedimentos_operation_date", "operation_date"),
        {"schema": _SCHEMA},
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.clients.id", ondelete="RESTRICT"), nullable=False
    )
    pedimento_number: Mapped[str] = mapped_column(sa.String(21), nullable=False, unique=True)
    customs_office: Mapped[str | None] = mapped_column(sa.String(3), nullable=True)
    pedimento_key: Mapped[str | None] = mapped_column(sa.String(3), nullable=True)
    regime: Mapped[str | None] = mapped_column(sa.String(3), nullable=True)
    trade_flow: Mapped[str] = mapped_column(check_enum(TRADE_FLOW, "trade_flow"), nullable=False)
    # Fecha de la operación: filtra qué regulación era vigente (§14 maestro).
    operation_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    entry_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    currency: Mapped[str] = mapped_column(_CCY, nullable=False, server_default="MXN")
    exchange_rate: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    customs_value: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    customs_value_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    total_taxes: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    total_taxes_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    is_simulation: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )


class PedimentoItem(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Partida del pedimento: lo que efectivamente se declaró por mercancía."""

    __tablename__ = "pedimento_items"
    __table_args__ = (
        sa.UniqueConstraint(
            "pedimento_id", "line_number", name="uq_pedimento_items_pedimento_id_line_number"
        ),
        {"schema": _SCHEMA},
    )

    pedimento_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.pedimentos.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.products.id", ondelete="SET NULL"), nullable=True
    )
    invoice_item_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.invoice_items.id", ondelete="SET NULL"), nullable=True
    )
    line_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Lo declarado va como texto: puede no existir como fracción vigente.
    declared_fraction_code: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    declared_nico_code: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    tariff_fraction_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("regulatory.tariff_fractions.id", ondelete="RESTRICT"), nullable=True
    )
    nico_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("regulatory.nicos.id", ondelete="RESTRICT"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    commercial_unit: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    customs_value: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    customs_value_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    # El precio pagado y los incrementables van aparte del valor en aduana
    # porque un pedimento imprime los tres, y la única forma de comprobar el
    # tercero es rehacer la suma de los dos primeros (art. 65 de la Ley
    # Aduanera). Con sólo `customs_value` no hay contra qué contrastarlo: el
    # espejo acababa copiando el declarado como esperado.
    price_paid: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    price_paid_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    incrementables: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    incrementables_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    igi_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    igi_amount_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    vat_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    vat_amount_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    applied_nom_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(16)), nullable=False, server_default="{}"
    )
    identifiers: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
