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
    """Metadatos de toda fila que es producto de una decisión de IA (§3 TAREA_P2).

    `model_provider` es NULL cuando la fila no nace de una llamada a un LLM:
    una regla determinista del RGI Engine, una corrección humana
    (`data_origin = HUMAN_VALIDATED`) o una decisión importada de un
    histórico. Pero si hubo llamada, el resto de su telemetría no puede
    faltar — eso lo impone `ai_call_completeness_check` en el
    `__table_args__` de cada tabla que hereda este mixin, no una columna
    `NOT NULL` (decisión de Persona 1: una columna NOT NULL habría obligado
    a inventar un valor de relleno en los casos sin modelo).
    """

    model_provider: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    attempts: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # 0.0000 a 1.0000.
    confidence: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 4), nullable=True)
    # DEFAULT true: el sistema falla hacia cautela (regla 2 CLAUDE.md). Bajarlo
    # a false es una decisión explícita del motor de clasificación con
    # evidencia suficiente, nunca el valor de partida.
    requires_human_review: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true()
    )


def ai_call_completeness_check() -> sa.CheckConstraint:
    """CHECK de `AIDecisionMixin`: si hubo llamada a un modelo, su telemetría viene completa.

    `model_provider IS NULL` es válido (decisión sin LLM). En cuanto hay
    proveedor, el resto de la telemetría de esa llamada no puede quedar a
    medias. Se repite por tabla —no vive en el mixin— porque `__table_args__`
    no se compone entre clases de una jerarquía de mixins en SQLAlchemy: cada
    subclase ya declara el suyo con sus propios índices y constraints.

    El nombre es solo `ai_call_complete`: `NAMING_CONVENTION` (`database/models/base.py`)
    ya antepone `ck_%(table_name)s_`, igual que con `check_enum`.
    """
    return sa.CheckConstraint(
        "model_provider IS NULL OR ("
        "model_name IS NOT NULL AND input_tokens IS NOT NULL AND "
        "output_tokens IS NOT NULL AND latency_ms IS NOT NULL AND "
        "attempts IS NOT NULL)",
        name="ai_call_complete",
    )


class SyntheticMixin:
    """Marca de dato sintético (§10 maestro): escenario + semilla reproducibles."""

    synthetic_scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.synthetic_scenarios.id", ondelete="RESTRICT"),
        nullable=True,
    )
    seed: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
