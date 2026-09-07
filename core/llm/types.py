"""Tipos de la capa de modelos.

`CallMetadata` no es adorno: `model_provider`, `model_name`, `prompt_version`,
tokens y latencia son campos del Canonical Model (§17 maestro; regla 4 de
TAREA_P3). Sin ellos una decisión no es auditable, y §49 exige poder responder
con qué modelo y qué versión de prompt se produjo cada conclusión.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["system", "user", "assistant"]

# `model_` es namespace protegido de Pydantic; los nombres vienen impuestos por
# el Canonical Model, así que se libera el namespace en vez de renombrar.
_CANONICAL_NAMES = ConfigDict(protected_namespaces=(), frozen=True)


class Message(BaseModel):
    """Un turno de conversación, independiente del proveedor."""

    model_config = _CANONICAL_NAMES

    role: Role
    content: str


class Usage(BaseModel):
    """Consumo de tokens de una llamada."""

    model_config = _CANONICAL_NAMES

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Tokens totales facturados por la llamada."""
        return self.input_tokens + self.output_tokens


class CallMetadata(BaseModel):
    """Trazabilidad de una llamada al modelo (§17 maestro)."""

    model_config = _CANONICAL_NAMES

    model_provider: str
    model_name: str
    prompt_id: str | None = None
    prompt_version: str | None = None
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    attempts: int = 1
    finish_reason: str | None = None
    called_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ModelResponse(BaseModel):
    """Salida de texto libre, siempre acompañada de su trazabilidad."""

    model_config = _CANONICAL_NAMES

    text: str
    metadata: CallMetadata


class StructuredResponse[T: BaseModel](BaseModel):
    """Salida ya validada contra un esquema Pydantic, con su trazabilidad.

    Devolver el modelo a secas perdería la metadata, y la regla 4 de la tarea
    exige registrarla en toda llamada. `.data` es el objeto validado.
    """

    model_config = _CANONICAL_NAMES

    data: T
    metadata: CallMetadata
