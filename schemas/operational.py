"""Contratos del esquema `operational`.

Todo importe es `Decimal`, nunca `float` (§22 maestro). Cada importe lleva su
moneda hermana `<campo>_currency`.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from schemas.base import (
    CanonicalModel,
    DataOriginFields,
    IdentifiedRead,
    SyntheticFields,
)
from schemas.enums import TradeFlow

# ISO-4217 alfabético. Espejo de `CHAR(3)` en la base.
CurrencyCode = Annotated[str, Field(min_length=3, max_length=3)]

# ── synthetic_scenarios ─────────────────────────────────────────────────────


class SyntheticScenarioBase(DataOriginFields):
    slug: str = Field(max_length=64)
    name: str
    description: str | None = None
    seed: int
    generator_version: str | None = None
    parameters: dict = Field(default_factory=dict)


class SyntheticScenarioCreate(SyntheticScenarioBase):
    pass


class SyntheticScenarioRead(SyntheticScenarioBase, IdentifiedRead):
    pass


class SyntheticScenarioUpdate(CanonicalModel):
    name: str | None = None
    description: str | None = None
    generator_version: str | None = None
    parameters: dict | None = None


# ── clients ─────────────────────────────────────────────────────────────────


class ClientBase(DataOriginFields, SyntheticFields):
    legal_name: str
    rfc: str | None = Field(default=None, max_length=13)
    country: str = Field(default="MX", max_length=2)
    industry: str | None = None
    address: dict | None = None
    is_active: bool = True


class ClientCreate(ClientBase):
    pass


class ClientRead(ClientBase, IdentifiedRead):
    pass


class ClientUpdate(CanonicalModel):
    legal_name: str | None = None
    rfc: str | None = None
    industry: str | None = None
    address: dict | None = None
    is_active: bool | None = None


# ── suppliers ───────────────────────────────────────────────────────────────


class SupplierBase(DataOriginFields, SyntheticFields):
    legal_name: str
    tax_id: str | None = Field(default=None, max_length=32)
    country: str = Field(max_length=2)
    manufacturer_name: str | None = None
    is_manufacturer: bool = False
    address: dict | None = None


class SupplierCreate(SupplierBase):
    pass


class SupplierRead(SupplierBase, IdentifiedRead):
    pass


class SupplierUpdate(CanonicalModel):
    legal_name: str | None = None
    tax_id: str | None = None
    manufacturer_name: str | None = None
    is_manufacturer: bool | None = None
    address: dict | None = None


# ── products ────────────────────────────────────────────────────────────────


class ProductBase(DataOriginFields, SyntheticFields):
    client_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    sku: str = Field(max_length=64)
    commercial_name: str
    description: str | None = None
    brand: str | None = None
    model: str | None = None
    manufacturer_name: str | None = None
    country_of_manufacture: str | None = Field(default=None, max_length=2)
    unit_of_measure: str | None = Field(default=None, max_length=8)


class ProductCreate(ProductBase):
    pass


class ProductRead(ProductBase, IdentifiedRead):
    pass


class ProductUpdate(CanonicalModel):
    supplier_id: uuid.UUID | None = None
    commercial_name: str | None = None
    description: str | None = None
    brand: str | None = None
    model: str | None = None
    manufacturer_name: str | None = None
    country_of_manufacture: str | None = None
    unit_of_measure: str | None = None


# ── invoices ────────────────────────────────────────────────────────────────


class InvoiceBase(DataOriginFields, SyntheticFields):
    client_id: uuid.UUID
    supplier_id: uuid.UUID
    invoice_number: str = Field(max_length=64)
    invoice_date: date
    incoterm: str | None = Field(default=None, max_length=3)
    currency: CurrencyCode
    subtotal_amount: Decimal | None = None
    subtotal_amount_currency: str | None = None
    freight_amount: Decimal | None = None
    freight_amount_currency: str | None = None
    insurance_amount: Decimal | None = None
    insurance_amount_currency: str | None = None
    total_amount: Decimal
    total_amount_currency: CurrencyCode


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceRead(InvoiceBase, IdentifiedRead):
    pass


class InvoiceUpdate(CanonicalModel):
    incoterm: str | None = None
    subtotal_amount: Decimal | None = None
    freight_amount: Decimal | None = None
    insurance_amount: Decimal | None = None
    total_amount: Decimal | None = None


# ── invoice_items ───────────────────────────────────────────────────────────


class InvoiceItemBase(DataOriginFields, SyntheticFields):
    invoice_id: uuid.UUID
    product_id: uuid.UUID | None = None
    line_number: int = Field(ge=1)
    description: str
    quantity: Decimal
    unit_of_measure: str | None = Field(default=None, max_length=8)
    country_of_origin: str | None = Field(default=None, max_length=2)
    unit_price: Decimal
    unit_price_currency: CurrencyCode
    line_total: Decimal
    line_total_currency: CurrencyCode


class InvoiceItemCreate(InvoiceItemBase):
    pass


class InvoiceItemRead(InvoiceItemBase, IdentifiedRead):
    pass


class InvoiceItemUpdate(CanonicalModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    country_of_origin: str | None = None


# ── coves ───────────────────────────────────────────────────────────────────


class CoveBase(DataOriginFields, SyntheticFields):
    invoice_id: uuid.UUID
    cove_number: str = Field(max_length=32)
    cove_type: str | None = Field(default=None, max_length=16)
    issued_at: date | None = None
    edocument_hash: str | None = None


class CoveCreate(CoveBase):
    pass


class CoveRead(CoveBase, IdentifiedRead):
    pass


class CoveUpdate(CanonicalModel):
    cove_type: str | None = None
    issued_at: date | None = None
    edocument_hash: str | None = None


# ── pedimentos ──────────────────────────────────────────────────────────────


class PedimentoBase(DataOriginFields, SyntheticFields):
    client_id: uuid.UUID
    pedimento_number: str = Field(max_length=21)
    customs_office: str | None = Field(default=None, max_length=3)
    pedimento_key: str | None = Field(default=None, max_length=3)
    regime: str | None = Field(default=None, max_length=3)
    trade_flow: TradeFlow
    # Fecha de la operación: filtra qué regulación era vigente (§14 maestro).
    operation_date: date
    entry_date: date | None = None
    currency: str = Field(default="MXN", min_length=3, max_length=3)
    exchange_rate: Decimal | None = None
    customs_value: Decimal | None = None
    customs_value_currency: str | None = None
    total_taxes: Decimal | None = None
    total_taxes_currency: str | None = None
    is_simulation: bool = False


class PedimentoCreate(PedimentoBase):
    pass


class PedimentoRead(PedimentoBase, IdentifiedRead):
    pass


class PedimentoUpdate(CanonicalModel):
    customs_office: str | None = None
    pedimento_key: str | None = None
    regime: str | None = None
    entry_date: date | None = None
    exchange_rate: Decimal | None = None
    customs_value: Decimal | None = None
    total_taxes: Decimal | None = None
    is_simulation: bool | None = None


# ── pedimento_items ─────────────────────────────────────────────────────────


class PedimentoItemBase(DataOriginFields, SyntheticFields):
    pedimento_id: uuid.UUID
    product_id: uuid.UUID | None = None
    invoice_item_id: uuid.UUID | None = None
    line_number: int = Field(ge=1)
    description: str
    declared_fraction_code: str | None = Field(default=None, max_length=8)
    declared_nico_code: str | None = Field(default=None, max_length=2)
    tariff_fraction_id: uuid.UUID | None = None
    nico_id: uuid.UUID | None = None
    quantity: Decimal
    commercial_unit: str | None = Field(default=None, max_length=8)
    country_of_origin: str | None = Field(default=None, max_length=2)
    customs_value: Decimal | None = None
    customs_value_currency: str | None = None
    igi_amount: Decimal | None = None
    igi_amount_currency: str | None = None
    vat_amount: Decimal | None = None
    vat_amount_currency: str | None = None
    applied_nom_codes: list[str] = Field(default_factory=list)
    identifiers: dict = Field(default_factory=dict)


class PedimentoItemCreate(PedimentoItemBase):
    pass


class PedimentoItemRead(PedimentoItemBase, IdentifiedRead):
    pass


class PedimentoItemUpdate(CanonicalModel):
    declared_fraction_code: str | None = None
    declared_nico_code: str | None = None
    tariff_fraction_id: uuid.UUID | None = None
    nico_id: uuid.UUID | None = None
    customs_value: Decimal | None = None
    igi_amount: Decimal | None = None
    vat_amount: Decimal | None = None
    applied_nom_codes: list[str] | None = None
    identifiers: dict | None = None
