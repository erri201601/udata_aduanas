"""Adaptador de Google Gemini sobre la API generativa.

Es el que más se aleja del formato común: roles `user`/`model`, `contents` en
vez de `messages` y el modelo en la URL. Todo eso queda encerrado aquí (§29).
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any, ClassVar

from core.llm.base import HTTPModelProvider
from core.llm.errors import ContentFilterError, ProviderResponseError
from core.llm.types import Usage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.llm.types import Message

MODEL_DEFAULT = "gemini-2.0-flash"
MODEL_EMBEDDING = "text-embedding-004"

# Gemini llama "model" a lo que el resto llama "assistant".
_ROLES = {"assistant": "model", "user": "user"}


class GeminiProvider(HTTPModelProvider):
    """Gemini vía `generateContent`."""

    name: ClassVar[str] = "gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    default_model: ClassVar[str] = MODEL_DEFAULT
    default_embedding_model: ClassVar[str | None] = MODEL_EMBEDDING

    def _headers(self) -> dict[str, str]:
        # La llave va en cabecera y no en la query: así no acaba escrita en los
        # logs de acceso de ningún proxy intermedio (§40 maestro).
        return {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}

    def _chat_url(self, model: str) -> str:
        return f"{self.base_url}/models/{model}:generateContent"

    def _chat_payload(
        self,
        messages: Sequence[Message],
        *,
        system: str | None,
        model: str,  # noqa: ARG002  (Gemini lo lleva en la URL)
        max_tokens: int,
        temperature: float | None,
    ) -> dict[str, Any]:
        contents = [
            {"role": _ROLES.get(m.role, "user"), "parts": [{"text": m.content}]}
            for m in messages
            if m.role != "system"
        ]
        inline_system = "\n\n".join(m.content for m in messages if m.role == "system")
        combined = "\n\n".join(filter(None, (system, inline_system)))

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if temperature is not None:
            payload["generationConfig"]["temperature"] = temperature
        if combined:
            payload["systemInstruction"] = {"parts": [{"text": combined}]}
        return payload

    def _parse_chat(self, data: dict[str, Any]) -> tuple[str, Usage, str | None]:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            # Sin candidatos, Gemini explica el bloqueo en promptFeedback.
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            if reason:
                raise ContentFilterError(
                    f"{self.name}: petición bloqueada ({reason})", provider=self.name
                )
            raise ProviderResponseError(
                f"{self.name}: la respuesta no trae 'candidates'", provider=self.name
            )

        first = candidates[0]
        finish_reason = first.get("finishReason")
        if finish_reason == "SAFETY":
            raise ContentFilterError(
                f"{self.name}: respuesta bloqueada por filtro de seguridad", provider=self.name
            )

        parts = (first.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        raw_usage = data.get("usageMetadata") or {}
        usage = Usage(
            input_tokens=int(raw_usage.get("promptTokenCount", 0)),
            output_tokens=int(raw_usage.get("candidatesTokenCount", 0)),
        )
        return text, usage, finish_reason

    def _image_payload(
        self,
        image: bytes,
        prompt: str,
        *,
        media_type: str,
        model: str,  # noqa: ARG002  (Gemini lo lleva en la URL)
        max_tokens: int,
    ) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": media_type,
                                "data": base64.b64encode(image).decode("ascii"),
                            }
                        },
                        {"text": prompt},
                    ],
                }
            ],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }

    def _embed_request(self, text: str, model: str) -> tuple[str, dict[str, Any]]:
        url = f"{self.base_url}/models/{model}:embedContent"
        return url, {"model": f"models/{model}", "content": {"parts": [{"text": text}]}}

    def _parse_embed(self, data: dict[str, Any]) -> list[float]:
        values = (data.get("embedding") or {}).get("values")
        if not isinstance(values, list):
            raise ProviderResponseError(
                f"{self.name}: la respuesta de embeddings no trae 'embedding.values'",
                provider=self.name,
            )
        return [float(v) for v in values]
