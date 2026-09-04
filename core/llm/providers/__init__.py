"""Adaptadores concretos.

Este es el único paquete de `core/` donde puede vivir el detalle de un
proveedor. Nada de aquí debe filtrarse al dominio (§29 maestro, regla 1 de
TAREA_P3); el dominio habla con `core.llm.ModelProvider`.
"""

from __future__ import annotations

from core.llm.providers.anthropic import AnthropicProvider
from core.llm.providers.gemini import GeminiProvider
from core.llm.providers.local import LocalProvider
from core.llm.providers.openai import OpenAIProvider

__all__ = ["AnthropicProvider", "GeminiProvider", "LocalProvider", "OpenAIProvider"]
