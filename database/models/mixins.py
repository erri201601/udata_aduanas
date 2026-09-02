"""Campos transversales del Canonical Data Model (§3 TAREA_P2).

Cada mixin es un bloque obligatorio de columnas que se repite en muchas tablas.
Componerlos evita divergencias: si el contrato dice que *toda* tabla regulatoria
lleva `content_hash`, aquí se define una sola vez.

Reglas que estos mixins imponen y no se pueden romper:
- `id` UUID con `DEFAULT gen_random_uuid()`.
- Timestamps siempre `TIMESTAMPTZ` (`DateTime(timezone=True)`), nunca naïve.
- `data_origin` con `CHECK` sobre los cinco valores de §9 maestro.
- `valid_to` NULL = sigue vigente. Nunca se inventa una fecha de fin.
- Enums vía `native_enum=False` -> `VARCHAR` + `CHECK`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from database.models.enums import DATA_ORIGIN


# Reutilizable en cualquier columna enumerada: VARCHAR + CHECK, sin tipo nativo.
def check_enum(values: tuple[str, ...], name: str) -> sa.Enum:
    """`sa.Enum` que Alembic materializa como `VARCHAR` + `CHECK` con nombre."""
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=max(len(v) for v in values),
        validate_strings=True,
    )


class UUIDPrimaryKeyMixin:
    """`id UUID PRIMARY KEY DEFAULT gen_random_uuid()` (§3 TAREA_P2)."""

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


class TimestampMixin:
    """`created_at` / `updated_at`, siempre `TIMESTAMPTZ NOT NULL DEFAULT now()`."""

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class DataOriginMixin:
    """`data_origin` (CHECK sobre los 5 valores) + `source_id` -> `legal_sources`.

    `source_id` es NULL cuando el dato no proviene de una fuente registrada
    (p. ej. un cliente sintético). La FK usa `RESTRICT`: una fuente no se borra
    si algo la referencia.
    """

    data_origin: Mapped[str] = mapped_column(
        check_enum(DATA_ORIGIN, "data_origin"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("regulatory.legal_sources.id", ondelete="RESTRICT"),
        nullable=True,
    )


class RegulatoryMixin:
    """Trazabilidad y vigencia de todo dato normativo (§3 TAREA_P2, §13 maestro).

    El índice por `(clave_natural, valid_from, valid_to)` que pide §14 del
    maestro se declara en cada tabla, porque la clave natural cambia.
    """

    published_at: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    valid_from: Mapped[date] = mapped_column(sa.Date, nullable=False)
    # NULL = sigue vigente. NUNCA se inventa una fecha de fin (§5 CLAUDE.md).
    valid_to: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    source_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_document: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # sha256 del contenido normalizado.
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class AIDecisionMixin:
    """Metadatos de toda fila que es producto de una decisión de IA (§3 TAREA_P2)."""

    model_provider: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # 0.0000 a 1.0000.
    confidence: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 4), nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )


class SyntheticMixin:
    """Marca de dato sintético (§10 maestro): escenario + semilla reproducibles."""

    synthetic_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.synthetic_scenarios.id", ondelete="RESTRICT"),
        nullable=True,
    )
    seed: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
