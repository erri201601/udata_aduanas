"""Esquema `regulatory` — dato normativo real (§2 TAREA_P2).

`data_origin` aquí sólo puede ser OFFICIAL / PUBLIC / LICENSED. Cada fila lleva
trazabilidad y vigencia (`RegulatoryMixin`). Nada de esto se inventa: si la
fuente no se pudo recuperar, la fila no existe (§8 maestro).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base
from database.models.enums import (
    LEGAL_DOCUMENT_KIND,
    REGULATORY_EVENT_KIND,
    SOURCE_KIND,
)
from database.models.mixins import (
    DataOriginMixin,
    RegulatoryMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    check_enum,
)

_SCHEMA = "regulatory"


class LegalSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fuente registrada: DOF, SNICE, Cámara de Diputados, CBP, EBTI, WCO…

    Es el ancla de trazabilidad: el `source_id` de todo el modelo apunta aquí
    (§8 Persona 1). No hereda `DataOriginMixin` — sería una autorreferencia.
    """

    __tablename__ = "legal_sources"
    __table_args__ = ({"schema": _SCHEMA},)

    slug: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    authority: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    jurisdiction: Mapped[str] = mapped_column(sa.String(2), nullable=False, server_default="MX")
    kind: Mapped[str] = mapped_column(check_enum(SOURCE_KIND, "source_kind"), nullable=False)
    base_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class LegalDocument(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Documento jurídico normalizado: LIGIE, Ley Aduanera, RGCE, Anexo 22, NOM…"""

    __tablename__ = "legal_documents"
    __table_args__ = (
        sa.Index("ix_legal_documents_vigencia", "short_name", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    short_name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    kind: Mapped[str] = mapped_column(
        check_enum(LEGAL_DOCUMENT_KIND, "legal_document_kind"), nullable=False
    )
    document_number: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    language: Mapped[str] = mapped_column(sa.String(2), nullable=False, server_default="es")
    reform_reference: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    full_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class LegalRule(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Unidad citable de un documento: un artículo, una regla RGCE, una RGI."""

    __tablename__ = "legal_rules"
    __table_args__ = (
        sa.Index("ix_legal_rules_vigencia", "rule_number", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    legal_document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.legal_documents.id", ondelete="RESTRICT"), nullable=False
    )
    rule_number: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    heading_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Marca la regla como una de las Reglas Generales de Interpretación (RGI 1..6).
    rgi_reference: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)


class TariffFraction(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Fracción arancelaria mexicana (8 dígitos).

    El código va como `VARCHAR`, nunca entero: los ceros a la izquierda importan.
    `chapter`/`heading`/`subheading`/`code` se guardan por separado para poder
    consultar por nivel (§4 TAREA_P2).
    """

    __tablename__ = "tariff_fractions"
    __table_args__ = (
        sa.Index("ix_tariff_fractions_vigencia", "code", "valid_from", "valid_to"),
        sa.Index("ix_tariff_fractions_niveles", "chapter", "heading", "subheading"),
        sa.UniqueConstraint("code", "valid_from", name="uq_tariff_fractions_code_valid_from"),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    chapter: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    heading: Mapped[str] = mapped_column(sa.String(4), nullable=False)
    subheading: Mapped[str] = mapped_column(sa.String(6), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(sa.String(4), nullable=True)
    # Tasas como fracción (0.16, no 16) — §2 TAREA_P2.
    igi_rate: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 6), nullable=True)
    ige_rate: Mapped[Decimal | None] = mapped_column(sa.Numeric(9, 6), nullable=True)
    legal_document_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.legal_documents.id", ondelete="RESTRICT"), nullable=True
    )
    # Qué tan específico es `description` frente a sus hermanas bajo la misma
    # subpartida/partida (RGI 3 a)). Mayor = más específico. 0 = catch-all
    # ("Los demás"/"Las demás"). Calculado por `ingestion.snice.tariff`, nunca
    # a mano — ver ahí la heurística exacta. Sin esto, TariffCatalog no puede
    # desempatar y todo cae a HUMAN_REVIEW_REQUIRED (Persona 1, 2026-09-07).
    specificity: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")


class Nico(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Número de Identificación Comercial: 2 dígitos más sobre la fracción."""

    __tablename__ = "nicos"
    __table_args__ = (
        sa.Index("ix_nicos_vigencia", "full_code", "valid_from", "valid_to"),
        sa.UniqueConstraint("full_code", "valid_from", name="uq_nicos_full_code_valid_from"),
        {"schema": _SCHEMA},
    )

    tariff_fraction_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.tariff_fractions.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    # Fracción (8) + NICO (2). VARCHAR, nunca entero.
    full_code: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    correlation: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class RegulatoryEvent(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Salida del DOF Regulatory Watcher: una publicación relevante y su alcance."""

    __tablename__ = "regulatory_events"
    __table_args__ = (
        sa.Index("ix_regulatory_events_vigencia", "event_kind", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    authority: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    event_kind: Mapped[str] = mapped_column(
        check_enum(REGULATORY_EVENT_KIND, "regulatory_event_kind"), nullable=False
    )
    effective_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False, server_default="{}")
    affected_fraction_codes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(8)), nullable=False, server_default="{}"
    )
    affected_rule_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=False, server_default="{}"
    )
