"""Traducción de la telemetría de una llamada a los campos del Canonical Model.

Acordado con Persona 2 (opción A): tokens, latencia e intentos se guardan como
columnas de `AIDecisionMixin`, no en una tabla aparte. Encaja con lo que esta
capa produce, porque `generate_structured()` ya acumula tokens y latencia a
través de los reintentos y devuelve el agregado de la decisión completa.

Este módulo devuelve un mapeo plano, no un modelo de `schemas`, a propósito:
`core/` no debe importar la capa de persistencia (§29). Quien escriba la fila
hace el ensamblado.

    from core.llm.canonical import to_canonical_fields

    respuesta = provider.generate_structured(...)
    fila = AIDecisionFields(**to_canonical_fields(respuesta.metadata))

Dos campos del mixin quedan fuera a conciencia:

`confidence` y `requires_human_review` no se derivan de aquí. Esta capa sólo
sabe que el modelo respondió y que la salida validó contra su esquema; la
confianza es un juicio del motor de clasificación. Los llena ese módulo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from core.llm.types import CallMetadata


class CanonicalAIFields(TypedDict):
    """Campos de `AIDecisionMixin` que esta capa sí puede llenar.

    `total_tokens` no está: es `input_tokens + output_tokens` y duplicarlo abre
    la puerta a que discrepen. Si hace falta en consultas va como columna
    generada de Postgres, no como dato escrito por la aplicación.

    `called_at` tampoco: `TimestampMixin` ya registra cuándo se creó la fila, y
    en v0.1 no hay caso donde ambos instantes difieran de forma significativa.
    """

    model_provider: str
    model_name: str
    prompt_id: str | None
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    attempts: int
    finish_reason: str | None


def to_canonical_fields(metadata: CallMetadata) -> CanonicalAIFields:
    """Convierte la metadata de una llamada en columnas del Canonical Model.

    Los nombres son los del contrato acordado, neutros entre proveedores:
    `input_tokens` / `output_tokens`, no la nomenclatura de OpenAI
    (`prompt_tokens` / `completion_tokens`), que ataría el modelo canónico a un
    proveedor concreto (§29).
    """
    return CanonicalAIFields(
        model_provider=metadata.model_provider,
        model_name=metadata.model_name,
        prompt_id=metadata.prompt_id,
        prompt_version=metadata.prompt_version,
        input_tokens=metadata.usage.input_tokens,
        output_tokens=metadata.usage.output_tokens,
        latency_ms=metadata.latency_ms,
        attempts=metadata.attempts,
        finish_reason=metadata.finish_reason,
    )
