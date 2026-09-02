"""Adaptador de Anthropic sobre la Messages API.

Hablamos HTTP directo en vez de usar el SDK: `core/` no arrastra ninguna
librería de proveedor y el contrato queda del lado nuestro (§29 maestro).
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any, ClassVar

from core.llm.base import HTTPModelProvider
from core.llm.errors import ProviderResponseError
from core.llm.types import Usage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.llm.types import Message

API_VERSION = "2023-06-01"

# Familia Claude 5. `claude-opus-5` para razonamiento largo y `claude-haiku-4-5`
# para volumen; sonnet es el equilibrio por defecto.
MODEL_OPUS = "claude-opus-5"
MODEL_SONNET = "claude-sonnet-5"
MODEL_HAIKU = "claude-haiku-4-5-20251001"


class AnthropicProvider(HTTPModelProvider):
    """Claude vía Messages API."""

    name: ClassVar[str] = "anthropic"
    base_url = "https://api.anthropic.com/v1"
    default_model: ClassVar[str] = MODEL_SONNET
    # Anthropic no publica endpoint de embeddings: se queda en None a propósito
    # y `embed()` lanza ProviderCapabilityError en vez de inventar un vector.
    default_embedding_model: ClassVar[str | None] = None

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    def _chat_url(self, model: str) -> str:  # noqa: ARG002  (la URL no lleva el modelo)
        return f"{self.base_url}/messages"

    def _chat_payload(
        self,
        messages: Sequence[Message],
        *,
        system: str | None,
        model: str,
        max_tokens: int,
        temperature: float | None,
    ) -> dict[str, Any]:
        # El system va en su propio campo, no como turno de la conversación.
        turns = [m for m in messages if m.role != "system"]
        inline_system = "\n\n".join(m.content for m in messages if m.role == "system")
        combined = "\n\n".join(filter(None, (system, inline_system)))

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in turns],
        }
        # Sólo se envía si se pide: los modelos recientes la rechazan y un
        # valor por defecto convertiría una llamada válida en un HTTP 400.
        if temperature is not None:
            payload["temperature"] = temperature
        if combined:
            payload["system"] = combined
        return payload

    def _parse_chat(self, data: dict[str, Any]) -> tuple[str, Usage, str | None]:
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise ProviderResponseError(
                "anthropic: la respuesta no trae 'content'", provider=self.name
            )
        text = "".join(
            b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
        )
        raw_usage = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(raw_usage.get("input_tokens", 0)),
            output_tokens=int(raw_usage.get("output_tokens", 0)),
        )
        return text, usage, data.get("stop_reason")

    def _image_payload(
        self,
        image: bytes,
        prompt: str,
        *,
        media_type: str,
        model: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        return {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(image).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
