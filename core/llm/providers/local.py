"""Hueco de `LocalProvider` — modelos en la propia infraestructura.

Existe porque §29 del maestro y TAREA_P3 lo piden explícitamente: el día que un
cliente exija que nada salga de su red, se enchufa aquí sin tocar `core/`.

Ollama, vLLM y llama.cpp exponen la API de Chat Completions de OpenAI, así que
el formato de mensajes se hereda y solo cambia la URL base.

NEEDS_VALIDATION: no se ha probado contra un servidor local real. Falta
decidir el endpoint por defecto del equipo y añadirlo a `.env`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from core.llm.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    import httpx

DEFAULT_BASE_URL = "http://localhost:11434/v1"


class LocalProvider(OpenAIProvider):
    """Modelo local tras una API compatible con OpenAI."""

    name: ClassVar[str] = "local"
    base_url = DEFAULT_BASE_URL
    # Sin default: el modelo lo decide quien levante el servidor, y adivinarlo
    # sería inventar (§36 maestro).
    default_model: ClassVar[str] = ""
    default_embedding_model: ClassVar[str | None] = None

    def __init__(
        self,
        api_key: str = "local",
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        # Un servidor local no suele pedir llave; se acepta un valor de relleno
        # para no obligar a poner un secreto falso en `.env`.
        if base_url:
            self.base_url = base_url
        if not model and not self.default_model:
            raise ValueError("LocalProvider necesita un `model` explícito: no hay default")
        super().__init__(api_key or "local", model=model, timeout=timeout, client=client)

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}
