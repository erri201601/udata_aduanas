"""Contratos del esquema `regulatory`."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from schemas.base import (
    CanonicalModel,
    DataOriginFields,
    IdentifiedRead,
    RegulatoryFields,
)
from schemas.enums import LegalDocumentKind, RegulatoryEventKind, SourceKind

# ── legal_sources ───────────────────────────────────────────────────────────


class LegalSourceBase(CanonicalModel):
    slug: str = Field(max_length=64)
    name: str
    authority: str | None = None
    jurisdiction: str = Field(default="MX", max_length=2)
    kind: SourceKind
    base_url: str | None = None
    notes: str | None = None


class LegalSourceCreate(LegalSourceBase):
    pass


class LegalSourceRead(LegalSourceBase, IdentifiedRead):
    pass


class LegalSourceUpdate(CanonicalModel):
    name: str | None = None
    authority: str | None = None
    kind: SourceKind | None = None
    base_url: str | None = None
    notes: str | None = None


# ── legal_documents ─────────────────────────────────────────────────────────


class LegalDocumentBase(DataOriginFields, RegulatoryFields):
    title: str
    short_name: str = Field(max_length=64)
    kind: LegalDocumentKind
    document_number: str | None = Field(default=None, max_length=128)
    language: str = Field(default="es", max_length=2)
    reform_reference: str | None = None
    full_text: str | None = None


class LegalDocumentCreate(LegalDocumentBase):
    pass


class LegalDocumentRead(LegalDocumentBase, IdentifiedRead):
    pass


class LegalDocumentUpdate(CanonicalModel):
    title: str | None = None
    valid_to: date | None = None
    reform_reference: str | None = None
    full_text: str | None = None


# ── legal_rules ─────────────────────────────────────────────────────────────


class LegalRuleBase(DataOriginFields, RegulatoryFields):
    legal_document_id: uuid.UUID
    rule_number: str = Field(max_length=64)
    path: str | None = None
    heading_text: str | None = None
    text: str
    rgi_reference: str | None = Field(default=None, max_length=8)


class LegalRuleCreate(LegalRuleBase):
    pass


class LegalRuleRead(LegalRuleBase, IdentifiedRead):
    pass


class LegalRuleUpdate(CanonicalModel):
    text: str | None = None
    path: str | None = None
    heading_text: str | None = None
    valid_to: date | None = None


# ── tariff_fractions ────────────────────────────────────────────────────────


class TariffFractionBase(DataOriginFields, RegulatoryFields):
    code: str = Field(max_length=8, pattern=r"^\d{8}$")
    chapter: str = Field(max_length=2)
    heading: str = Field(max_length=4)
    subheading: str = Field(max_length=6)
    description: str
    unit: str | None = Field(default=None, max_length=4)
    # Tasas como fracción (0.16, no 16). Decimal, nunca float (§22 maestro).
    igi_rate: Decimal | None = None
    ige_rate: Decimal | None = None
    legal_document_id: uuid.UUID | None = None
    # Qué tan específico es `description` frente a sus hermanas (RGI 3 a)).
    specificity: int = 0


class TariffFractionCreate(TariffFractionBase):
    pass


class TariffFractionRead(TariffFractionBase, IdentifiedRead):
    pass


class TariffFractionUpdate(CanonicalModel):
    description: str | None = None
    unit: str | None = None
    igi_rate: Decimal | None = None
    ige_rate: Decimal | None = None
    valid_to: date | None = None


# ── nicos ───────────────────────────────────────────────────────────────────


class NicoBase(DataOriginFields, RegulatoryFields):
    tariff_fraction_id: uuid.UUID
    code: str = Field(max_length=2, pattern=r"^\d{2}$")
    full_code: str = Field(max_length=10, pattern=r"^\d{10}$")
    description: str
    correlation: str | None = None


class NicoCreate(NicoBase):
    pass


class NicoRead(NicoBase, IdentifiedRead):
    pass


class NicoUpdate(CanonicalModel):
    description: str | None = None
    correlation: str | None = None
    valid_to: date | None = None


# ── customs_offices ─────────────────────────────────────────────────────────


class CustomsOfficeBase(DataOriginFields, RegulatoryFields):
    aduana: str = Field(max_length=2)
    seccion: str | None = Field(default=None, max_length=2)
    name: str


class CustomsOfficeCreate(CustomsOfficeBase):
    pass


class CustomsOfficeRead(CustomsOfficeBase, IdentifiedRead):
    pass


class CustomsOfficeUpdate(CanonicalModel):
    name: str | None = None
    valid_to: date | None = None


# ── units_of_measure ────────────────────────────────────────────────────────


class UnitOfMeasureBase(DataOriginFields, RegulatoryFields):
    code: str = Field(max_length=2)
    description: str


class UnitOfMeasureCreate(UnitOfMeasureBase):
    pass


class UnitOfMeasureRead(UnitOfMeasureBase, IdentifiedRead):
    pass


class UnitOfMeasureUpdate(CanonicalModel):
    description: str | None = None
    valid_to: date | None = None


# ── pedimento_claves ────────────────────────────────────────────────────────


class PedimentoClaveBase(DataOriginFields, RegulatoryFields):
    code: str = Field(max_length=3)
    # NULL = pendiente de cargar (deuda técnica), nunca "sin etiqueta"/"sin
    # supuestos" — ver el comentario de columna en database/models/regulatory.py.
    label: str | None = None
    supuestos_de_aplicacion: str | None = None


class PedimentoClaveCreate(PedimentoClaveBase):
    pass


class PedimentoClaveRead(PedimentoClaveBase, IdentifiedRead):
    pass


class PedimentoClaveUpdate(CanonicalModel):
    label: str | None = None
    supuestos_de_aplicacion: str | None = None
    valid_to: date | None = None


# ── non_tariff_regulations ──────────────────────────────────────────────────


class NonTariffRegulationBase(DataOriginFields, RegulatoryFields):
    code: str = Field(max_length=2)
    issuing_agency: str
    description: str


class NonTariffRegulationCreate(NonTariffRegulationBase):
    pass


class NonTariffRegulationRead(NonTariffRegulationBase, IdentifiedRead):
    pass


class NonTariffRegulationUpdate(CanonicalModel):
    description: str | None = None
    valid_to: date | None = None


# ── regulatory_events ───────────────────────────────────────────────────────


class RegulatoryEventBase(DataOriginFields, RegulatoryFields):
    title: str
    authority: str | None = None
    event_kind: RegulatoryEventKind
    effective_date: date | None = None
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    affected_fraction_codes: list[str] = Field(default_factory=list)
    affected_rule_ids: list[uuid.UUID] = Field(default_factory=list)


class RegulatoryEventCreate(RegulatoryEventBase):
    pass


class RegulatoryEventRead(RegulatoryEventBase, IdentifiedRead):
    pass


class RegulatoryEventUpdate(CanonicalModel):
    summary: str | None = None
    keywords: list[str] | None = None
    affected_fraction_codes: list[str] | None = None
    affected_rule_ids: list[uuid.UUID] | None = None
    valid_to: date | None = None
