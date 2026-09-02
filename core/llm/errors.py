"""Errores de la capa de modelos (§29 maestro; regla 5 de TAREA_P3).

Un fallo de proveedor nunca se convierte en un ``None`` silencioso: cada modo
de fallo tiene su excepción para que el dominio decida qué hacer con cada uno.
Un rate limit se reintenta; un filtro de contenido escala a revisión humana;
una llave ausente deshabilita el proveedor. No son el mismo problema.
"""

from __future__ import annotations


class ModelProviderError(Exception):
    """Raíz de todos los fallos de la capa de modelos."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderNotConfiguredError(ModelProviderError):
    """El proveedor no tiene llave en `.env`.

    Se lanza al construirlo, nunca al importarlo: un proveedor sin credencial
    queda deshabilitado y el resto del sistema sigue arrancando.
    """


class ProviderAuthenticationError(ModelProviderError):
    """La llave existe pero el proveedor la rechaza (401/403)."""


class ProviderTimeoutError(ModelProviderError):
    """El proveedor no respondió dentro del timeout."""


class ProviderRateLimitError(ModelProviderError):
    """429. `retry_after_seconds` sale de la cabecera cuando el proveedor la envía."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.retry_after_seconds = retry_after_seconds


class ContentFilterError(ModelProviderError):
    """El proveedor bloqueó la petición o la respuesta por filtro de contenido."""


class ProviderResponseError(ModelProviderError):
    """Respuesta inesperada: HTTP no contemplado, o cuerpo que no encaja."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.status_code = status_code


class StructuredOutputError(ModelProviderError):
    """`generate_structured` agotó los reintentos sin producir salida válida.

    Conserva la última salida cruda y el error de validación: sin eso es
    imposible depurar por qué un prompt dejó de producir JSON válido.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        attempts: int = 0,
        raw_output: str | None = None,
        validation_error: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.attempts = attempts
        self.raw_output = raw_output
        self.validation_error = validation_error


class ProviderCapabilityError(ModelProviderError):
    """El proveedor no ofrece esa capacidad.

    Anthropic, por ejemplo, no expone un endpoint de embeddings. Fingir el
    soporte devolviendo un vector vacío sería inventar (§36 maestro).
    """
