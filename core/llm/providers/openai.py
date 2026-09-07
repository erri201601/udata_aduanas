"""Adaptador de OpenAI sobre la Chat Completions API.

Sin SDK, por la misma razón que el resto de adaptadores (§29 maestro). El
formato de mensajes de esta API es el que replican casi todos los servidores
locales, así que `LocalProvider` hereda de aquí.
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

MODEL_DEFAULT = "gpt-4o"
MODEL_EMBEDDING = "text-embedding-3-small"


class OpenAIProvider(HTTPModelProvider):
    """GPT vía Chat Completions."""

    name: ClassVar[str] = "openai"
    base_url = "https://api.openai.com/v1"
    default_model: ClassVar[str] = MODEL_DEFAULT
    default_embedding_model: ClassVar[str | None] = MODEL_EMBEDDING

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _chat_url(self, model: str) -> str:  # noqa: ARG002  (la URL no lleva el modelo)
        return f"{self.base_url}/chat/completions"

    def _chat_payload(
        self,
        messages: Sequence[Message],
        *,
        system: str | None,
        model: str,
        max_tokens: int,
        temperature: float | None,
    ) -> dict[str, Any]:
        turns: list[dict[str, Any]] = []
        if system:
            turns.append({"role": "system", "content": system})
        turns.extend({"role": m.role, "content": m.content} for m in messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": turns,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    def _parse_chat(self, data: dict[str, Any]) -> tuple[str, Usage, str | None]:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError(
                f"{self.name}: la respuesta no trae 'choices'", provider=self.name
            )
        first = choices[0]
        text = (first.get("message") or {}).get("content") or ""
        raw_usage = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(raw_usage.get("prompt_tokens", 0)),
            output_tokens=int(raw_usage.get("completion_tokens", 0)),
        )
        return text, usage, first.get("finish_reason")

    def _image_payload(
        self,
        image: bytes,
        prompt: str,
        *,
        media_type: str,
        model: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image).decode("ascii")
        return {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
        }

    def _embed_request(self, text: str, model: str) -> tuple[str, dict[str, Any]]:
        return f"{self.base_url}/embeddings", {"model": model, "input": text}

    def _parse_embed(self, data: dict[str, Any]) -> list[float]:
        entries = data.get("data")
        if not isinstance(entries, list) or not entries:
            raise ProviderResponseError(
                f"{self.name}: la respuesta de embeddings no trae 'data'", provider=self.name
            )
        return [float(v) for v in entries[0].get("embedding", [])]
