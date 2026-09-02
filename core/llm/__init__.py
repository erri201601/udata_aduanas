"""Capa de modelos de ADUANERO OS (§29 maestro).

Superficie pública: el dominio importa de aquí y de ningún sitio más. Cambiar
de proveedor —o mover todo a un modelo local— no debe obligar a tocar una línea
del resto de `core/`.

    from core.llm import Message, get_default_provider

    provider = get_default_provider()
    respuesta = provider.generate([Message(role="user", content="...")])
    respuesta.metadata.model_name      # trazabilidad de §17, siempre presente
"""

from __future__ import annotations

from core.llm.base import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_STRUCTURED_ATTEMPTS,
    DEFAULT_TIMEOUT_SECONDS,
    HTTPModelProvider,
    ModelProvider,
)
from core.llm.errors import (
    ContentFilterError,
    ModelProviderError,
    ProviderAuthenticationError,
    ProviderCapabilityError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    StructuredOutputError,
)
from core.llm.registry import (
    PROVIDERS,
    available_providers,
    build_provider,
    get_default_provider,
)
from core.llm.types import (
    CallMetadata,
    Message,
    ModelResponse,
    Role,
    StructuredResponse,
    Usage,
)

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_STRUCTURED_ATTEMPTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "PROVIDERS",
    "CallMetadata",
    "ContentFilterError",
    "HTTPModelProvider",
    "Message",
    "ModelProvider",
    "ModelProviderError",
    "ModelResponse",
    "ProviderAuthenticationError",
    "ProviderCapabilityError",
    "ProviderNotConfiguredError",
    "ProviderRateLimitError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "Role",
    "StructuredOutputError",
    "StructuredResponse",
    "Usage",
    "available_providers",
    "build_provider",
    "get_default_provider",
]
