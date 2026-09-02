"""Interfaz `ModelProvider` y base común de los adaptadores (§29 maestro).

El objetivo declarado en TAREA_P3 es que cambiar de proveedor —o mover todo a
un modelo local— no obligue a tocar una línea de `core/`. Por eso el dominio
habla con el `Protocol` de aquí abajo y nunca con un cliente concreto.

Los adaptadores se implementan sobre `httpx`, que ya es dependencia del
proyecto, en lugar de sobre los SDK de cada proveedor: así `core/` no arrastra
ninguna librería de tercero y el contrato queda en nuestras manos.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, TypeVar, runtime_checkable

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from core.llm.errors import (
    ContentFilterError,
    ProviderAuthenticationError,
    ProviderCapabilityError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    StructuredOutputError,
)
from core.llm.structured import repair_prompt, schema_instruction, validate_payload
from core.llm.types import CallMetadata, Message, ModelResponse, StructuredResponse, Usage

if TYPE_CHECKING:
    from collections.abc import Sequence

T = TypeVar("T", bound=BaseModel)

log = structlog.stdlib.get_logger("core.llm")

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_STRUCTURED_ATTEMPTS = 3


@runtime_checkable
class ModelProvider(Protocol):
    """Contrato único de la capa de modelos.

    Todo lo que `core/` necesita de un LLM está aquí. Cualquier cosa que un
    proveedor haga y no quepa en esta interfaz no debe filtrarse al dominio.
    """

    name: str

    def generate(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = ...,
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float | None = ...,
    ) -> ModelResponse:
        """Texto libre a partir de una conversación."""
        ...

    def generate_structured(
        self,
        messages: Sequence[Message],
        schema: type[T],
        *,
        system: str | None = ...,
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float | None = ...,
        max_attempts: int = ...,
    ) -> StructuredResponse[T]:
        """Salida validada contra un modelo Pydantic, con reintentos."""
        ...

    def embed(self, text: str, *, model: str | None = ...) -> list[float]:
        """Vector de un texto."""
        ...

    def analyze_image(
        self,
        image: bytes,
        prompt: str,
        *,
        media_type: str = ...,
        model: str | None = ...,
        max_tokens: int = ...,
    ) -> ModelResponse:
        """Lectura de una imagen: ficha técnica escaneada, foto de producto."""
        ...


class HTTPModelProvider(ABC):
    """Base de los adaptadores HTTP: transporte, errores y reintentos comunes.

    Cada proveedor concreto solo aporta su formato de petición y respuesta. La
    política de errores y el bucle de validación viven aquí una sola vez.
    """

    name: ClassVar[str]
    # Sin ClassVar: un proveedor puede apuntar a otro host por instancia.
    base_url: str
    default_model: ClassVar[str]
    default_embedding_model: ClassVar[str | None] = None

    def __init__(
        self,
        api_key: str,
        *,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(
                f"{self.name}: falta la llave en .env; el proveedor queda deshabilitado",
                provider=self.name,
            )
        self._api_key = api_key
        self._model = model or self.default_model
        self._timeout = timeout
        # El cliente se inyecta en los tests con httpx.MockTransport: la suite
        # no hace ni una llamada real (regla 6 de TAREA_P3).
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    # ── Ganchos que implementa cada proveedor ────────────────────────────────

    @abstractmethod
    def _headers(self) -> dict[str, str]:
        """Cabeceras de autenticación del proveedor."""

    @abstractmethod
    def _chat_url(self, model: str) -> str:
        """URL absoluta del endpoint de conversación."""

    @abstractmethod
    def _chat_payload(
        self,
        messages: Sequence[Message],
        *,
        system: str | None,
        model: str,
        max_tokens: int,
        temperature: float | None,
    ) -> dict[str, Any]:
        """Cuerpo de la petición de conversación."""

    @abstractmethod
    def _parse_chat(self, data: dict[str, Any]) -> tuple[str, Usage, str | None]:
        """Extrae (texto, tokens, finish_reason) de la respuesta cruda."""

    @abstractmethod
    def _image_payload(
        self,
        image: bytes,
        prompt: str,
        *,
        media_type: str,
        model: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Cuerpo de la petición multimodal."""

    def _embed_request(self, text: str, model: str) -> tuple[str, dict[str, Any]]:  # noqa: ARG002
        """(URL, cuerpo) de la petición de embeddings.

        Por defecto, sin soporte: un proveedor que no ofrece embeddings lo dice,
        no devuelve un vector inventado.
        """
        raise ProviderCapabilityError(
            f"{self.name}: no expone endpoint de embeddings", provider=self.name
        )

    def _parse_embed(self, data: dict[str, Any]) -> list[float]:  # noqa: ARG002
        """Extrae el vector de la respuesta cruda."""
        raise ProviderCapabilityError(
            f"{self.name}: no expone endpoint de embeddings", provider=self.name
        )

    # ── Superficie pública ───────────────────────────────────────────────────

    def generate(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
    ) -> ModelResponse:
        """Texto libre, con la trazabilidad de §17 ya rellena."""
        chosen = model or self._model
        payload = self._chat_payload(
            messages,
            system=system,
            model=chosen,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        started = time.perf_counter()
        data = self._post(self._chat_url(chosen), payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        text, usage, finish_reason = self._parse_chat(data)
        metadata = CallMetadata(
            model_provider=self.name,
            model_name=chosen,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            usage=usage,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
        log.info(
            "llm.generate",
            model_provider=self.name,
            model_name=chosen,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
        return ModelResponse(text=text, metadata=metadata)

    def generate_structured(
        self,
        messages: Sequence[Message],
        schema: type[T],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
        max_attempts: int = DEFAULT_STRUCTURED_ATTEMPTS,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
    ) -> StructuredResponse[T]:
        """Salida validada contra `schema`, reintentando con el error como pista.

        Nunca devuelve JSON sin validar (regla 3). Si agota los intentos lanza
        `StructuredOutputError` con la última salida cruda, porque sin ella no
        hay forma de depurar por qué un prompt dejó de funcionar.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1")

        conversation = list(messages)
        full_system = "\n\n".join(filter(None, (system, schema_instruction(schema))))
        total = Usage()
        latency_ms = 0
        raw = ""
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            response = self.generate(
                conversation,
                system=full_system,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
            )
            raw = response.text
            total = Usage(
                input_tokens=total.input_tokens + response.metadata.usage.input_tokens,
                output_tokens=total.output_tokens + response.metadata.usage.output_tokens,
            )
            latency_ms += response.metadata.latency_ms

            try:
                data = validate_payload(raw, schema)
            except ValidationError as exc:
                last_error = str(exc)
                log.warning(
                    "llm.structured.invalid",
                    model_provider=self.name,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    schema=schema.__name__,
                    error=last_error[:500],
                )
                if attempt == max_attempts:
                    break
                conversation = [
                    *conversation,
                    Message(role="assistant", content=raw),
                    Message(role="user", content=repair_prompt(schema, last_error, raw)),
                ]
                continue

            return StructuredResponse[schema](  # type: ignore[valid-type]
                data=data,
                metadata=CallMetadata(
                    model_provider=self.name,
                    model_name=response.metadata.model_name,
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    usage=total,
                    latency_ms=latency_ms,
                    attempts=attempt,
                    finish_reason=response.metadata.finish_reason,
                ),
            )

        raise StructuredOutputError(
            f"{self.name}: la salida no validó contra {schema.__name__} "
            f"tras {max_attempts} intento(s)",
            provider=self.name,
            attempts=max_attempts,
            raw_output=raw,
            validation_error=last_error,
        )

    def embed(self, text: str, *, model: str | None = None) -> list[float]:
        """Vector del texto. Lanza `ProviderCapabilityError` si no hay soporte."""
        chosen = model or self.default_embedding_model
        if chosen is None:
            raise ProviderCapabilityError(
                f"{self.name}: no expone endpoint de embeddings", provider=self.name
            )
        url, payload = self._embed_request(text, chosen)
        return self._parse_embed(self._post(url, payload))

    def analyze_image(
        self,
        image: bytes,
        prompt: str,
        *,
        media_type: str = "image/jpeg",
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
    ) -> ModelResponse:
        """Lectura de imagen (ficha técnica escaneada, foto de producto)."""
        chosen = model or self._model
        payload = self._image_payload(
            image,
            prompt,
            media_type=media_type,
            model=chosen,
            max_tokens=max_tokens,
        )
        started = time.perf_counter()
        data = self._post(self._chat_url(chosen), payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        text, usage, finish_reason = self._parse_chat(data)
        log.info(
            "llm.analyze_image",
            model_provider=self.name,
            model_name=chosen,
            media_type=media_type,
            image_bytes=len(image),
            latency_ms=latency_ms,
        )
        return ModelResponse(
            text=text,
            metadata=CallMetadata(
                model_provider=self.name,
                model_name=chosen,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                usage=usage,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
            ),
        )

    def close(self) -> None:
        """Cierra el cliente HTTP si lo creó este proveedor."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HTTPModelProvider:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ── Transporte ───────────────────────────────────────────────────────────

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST con la política de errores común a todos los proveedores."""
        try:
            response = self._client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"{self.name}: sin respuesta en {self._timeout}s", provider=self.name
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(
                f"{self.name}: fallo de transporte: {exc}", provider=self.name
            ) from exc

        self._raise_for_status(response)

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"{self.name}: la respuesta no es JSON",
                provider=self.name,
                status_code=response.status_code,
            ) from exc
        return body

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Traduce el HTTP a las excepciones propias de la regla 5."""
        if response.is_success:
            return

        detail = response.text[:300]
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            raise ProviderRateLimitError(
                f"{self.name}: rate limit — {detail}",
                provider=self.name,
                retry_after_seconds=float(retry_after) if _is_number(retry_after) else None,
            )
        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(
                f"{self.name}: credencial rechazada ({response.status_code})",
                provider=self.name,
            )
        if self._is_content_filter(response):
            raise ContentFilterError(
                f"{self.name}: bloqueado por filtro de contenido — {detail}",
                provider=self.name,
            )
        raise ProviderResponseError(
            f"{self.name}: HTTP {response.status_code} — {detail}",
            provider=self.name,
            status_code=response.status_code,
        )

    def _is_content_filter(self, response: httpx.Response) -> bool:
        """¿El error corresponde a un filtro de contenido? Cada API lo marca distinto."""
        if response.status_code != 400:
            return False
        return "content" in response.text.lower() and (
            "polic" in response.text.lower() or "filter" in response.text.lower()
        )


def _is_number(value: str | None) -> bool:
    """¿La cabecera trae un número usable?"""
    if value is None:
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True
