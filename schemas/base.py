"""Bloques base de los contratos Pydantic.

`CanonicalModel` fija la configuración común; los mixins replican los campos
transversales de `database/models/mixins.py` en el lado del contrato.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from schemas.enums import DataOrigin


class CanonicalModel(BaseModel):
    """Config común: lee desde atributos ORM, prohíbe campos extra."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class IdentifiedRead(CanonicalModel):
    """Campos que sólo existen al leer: clave e instantes de auditoría."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DataOriginFields(CanonicalModel):
    """`data_origin` obligatorio + `source_id` opcional (§9 maestro)."""

    data_origin: DataOrigin
    source_id: uuid.UUID | None = None


class RegulatoryFields(CanonicalModel):
    """Trazabilidad y vigencia de todo dato normativo (§13 maestro)."""

    published_at: date | None = None
    valid_from: date
    # NULL = sigue vigente. Nunca se inventa una fecha de fin.
    valid_to: date | None = None
    source_url: str
    source_document: str | None = None
    content_hash: str
    retrieved_at: datetime


class AIDecisionFields(CanonicalModel):
    """Metadatos de una fila producto de IA (§3 TAREA_P2)."""

    model_provider: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    requires_human_review: bool = False


class SyntheticFields(CanonicalModel):
    """Marca de dato sintético reproducible (§10 maestro)."""

    synthetic_scenario_id: uuid.UUID | None = None
    seed: int | None = None
