"""Construcción de proveedores a partir de la configuración.

Un proveedor sin llave en `.env` queda deshabilitado, no revienta (regla 2 de
TAREA_P3): importar este módulo nunca falla, y `available_providers()` permite
preguntar qué hay disponible antes de intentar usarlo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from core.llm.errors import ProviderNotConfiguredError
from core.llm.providers import (
    AnthropicProvider,
    GeminiProvider,
    LocalProvider,
    OpenAIProvider,
)

if TYPE_CHECKING:
    from core.llm.base import HTTPModelProvider

log = structlog.stdlib.get_logger("core.llm.registry")

PROVIDERS: dict[str, type[HTTPModelProvider]] = {
    AnthropicProvider.name: AnthropicProvider,
    OpenAIProvider.name: OpenAIProvider,
    GeminiProvider.name: GeminiProvider,
    LocalProvider.name: LocalProvider,
}

# Nombre del proveedor -> atributo de Settings que guarda su llave.
_KEY_FIELDS = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "google_api_key",
}


def _settings() -> Any:
    """Carga la configuración.

    El import es perezoso a propósito: `core/` no debe depender de `apps/` en
    tiempo de importación, y así `core.llm` se puede usar sin levantar la API.
    """
    from apps.api.config import get_settings

    return get_settings()


def api_key_for(name: str, settings: Any | None = None) -> str:
    """Llave configurada para un proveedor; cadena vacía si no hay."""
    field = _KEY_FIELDS.get(name)
    if field is None:
        return ""
    secret = getattr(settings or _settings(), field, None)
    return secret.get_secret_value() if secret is not None else ""


def available_providers(settings: Any | None = None) -> dict[str, bool]:
    """Qué proveedores tienen credencial. No construye nada ni lanza errores."""
    resolved = settings or _settings()
    return {name: bool(api_key_for(name, resolved)) for name in _KEY_FIELDS}


def build_provider(
    name: str | None = None,
    *,
    api_key: str | None = None,
    settings: Any | None = None,
    **kwargs: Any,
) -> HTTPModelProvider:
    """Instancia un proveedor por nombre.

    Sin `name` usa `DEFAULT_MODEL_PROVIDER` de `.env`. Lanza
    `ProviderNotConfiguredError` si falta la llave — nunca devuelve algo a
    medias.
    """
    resolved = settings or _settings()
    chosen: str = name or str(getattr(resolved, "default_model_provider", "anthropic"))

    provider_class = PROVIDERS.get(chosen)
    if provider_class is None:
        raise ProviderNotConfiguredError(
            f"proveedor desconocido: {chosen!r}; disponibles: {sorted(PROVIDERS)}",
            provider=chosen,
        )

    key = api_key if api_key is not None else api_key_for(chosen, resolved)
    log.info("llm.provider.build", model_provider=chosen, configured=bool(key))
    return provider_class(key, **kwargs)


def get_default_provider(**kwargs: Any) -> HTTPModelProvider:
    """Proveedor por defecto del proyecto, según `.env`."""
    return build_provider(**kwargs)
