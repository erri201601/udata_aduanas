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


class CustomsOffice(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Aduana y sección aduanera (Apéndice 1, Anexo 22 RGCE).

    `aduana` no basta como llave: es un catálogo de 2 dígitos que se repite
    entre secciones distintas de la misma aduana (Persona 1, 2026-09-08 —
    mismo problema que resolvió Opción B para las 4 tablas del Anexo 22).
    `seccion` es NULL en las ~12 aduanas del documento real que no traen
    número de sección propio (p. ej. instalaciones satélite de la aduana
    17/Matamoros) — es el dato tal como lo publica el DOF, no un hueco de
    parseo.
    """

    __tablename__ = "customs_offices"
    __table_args__ = (
        sa.Index("ix_customs_offices_vigencia", "aduana", "seccion", "valid_from", "valid_to"),
        sa.UniqueConstraint("aduana", "seccion", name="uq_customs_offices_aduana_seccion"),
        {"schema": _SCHEMA},
    )

    aduana: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    seccion: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)


class UnitOfMeasure(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Unidad de medida del pedimento (Apéndice 7, Anexo 22 RGCE).

    `code` se ve numérico (1 = Kilo, 2 = Gramo…) pero va como `VARCHAR`, igual
    que las fracciones: es un código, no una cantidad (Persona 1, 2026-09-08).
    """

    __tablename__ = "units_of_measure"
    __table_args__ = (
        sa.Index("ix_units_of_measure_vigencia", "code", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(2), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)


class PedimentoClave(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Clave de pedimento (Apéndice 2, Anexo 22 RGCE).

    `code` se extrae de forma mecánica y confiable (66 claves verificadas).
    `label` y `supuestos_de_aplicacion` quedan NULL a propósito: el PDF del
    DOF presenta la etiqueta y la lista de supuestos de aplicación en dos
    columnas visuales lado a lado, y `pdftotext -layout` las intercala en el
    mismo renglón de texto sin ningún separador confiable — se probó folio
    por folio (numeral romano como falso punto final, columnas sin hueco
    detectable) y no hay heurística de texto que las separe sin inventar
    contenido. Requiere extracción por coordenadas (p. ej. `pdfplumber` sobre
    las cajas de palabras) o transcripción manual — deuda documentada, mismo
    criterio que las notas de capítulo de la LIGIE.
    """

    __tablename__ = "pedimento_claves"
    __table_args__ = (
        sa.Index("ix_pedimento_claves_vigencia", "code", "valid_from", "valid_to"),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(3), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment=(
            "Pendiente de cargar (deuda técnica): el layout de 2 columnas del "
            "PDF impide separar la etiqueta de los supuestos de forma "
            "confiable. NULL = no cargado, nunca 'sin etiqueta'."
        ),
    )
    supuestos_de_aplicacion: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment=(
            "Pendiente de cargar (deuda técnica). Toda clave tiene supuestos "
            "de aplicación en el documento real: NULL significa inequívocamente "
            "'no cargado', nunca 'no tiene' (Persona 1, 2026-09-08)."
        ),
    )


class NonTariffRegulation(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, RegulatoryMixin, Base):
    """Identificador de regulación o restricción no arancelaria (Apéndice 9).

    `code` se repite entre dependencias que emiten sus propios identificadores
    con la misma clave de 2 caracteres — confirmado en el documento real:
    "C1" y "C6" existen tanto bajo Secretaría de Economía como bajo Secretaría
    de Energía, con significados distintos. La llave natural es
    `(code, issuing_agency)`, no `code` solo.
    """

    __tablename__ = "non_tariff_regulations"
    __table_args__ = (
        sa.Index(
            "ix_non_tariff_regulations_vigencia", "code", "issuing_agency", "valid_from", "valid_to"
        ),
        sa.UniqueConstraint(
            "code", "issuing_agency", name="uq_non_tariff_regulations_code_agency"
        ),
        {"schema": _SCHEMA},
    )

    code: Mapped[str] = mapped_column(sa.String(2), nullable=False)
    issuing_agency: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)


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
