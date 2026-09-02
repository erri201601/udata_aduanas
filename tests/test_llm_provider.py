"""Adaptadores de la capa de modelos.

Toda la suite usa `httpx.MockTransport`: no sale una sola petición a la red
(regla 6 de TAREA_P3).
"""

from __future__ import annotations

import json

import httpx
import pytest
from core.llm import (
    ContentFilterError,
    Message,
    ProviderAuthenticationError,
    ProviderCapabilityError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    available_providers,
    build_provider,
)

# Las clases concretas se importan de `core.llm.providers` a propósito: el
# dominio habla con la abstracción, y sólo los tests del adaptador miran dentro.
from core.llm.providers import AnthropicProvider, GeminiProvider, OpenAIProvider


def _client(handler) -> httpx.Client:
    """Cliente httpx que responde con `handler` sin tocar la red."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _anthropic_ok(text: str = "hola", *, capture: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 11, "output_tokens": 7},
                "stop_reason": "end_turn",
            },
        )

    return handler


# ── Contrato básico ──────────────────────────────────────────────────────────


def test_generate_devuelve_texto_y_trazabilidad() -> None:
    provider = AnthropicProvider("llave-de-prueba", client=_client(_anthropic_ok("clasificado")))

    respuesta = provider.generate([Message(role="user", content="describe")])

    assert respuesta.text == "clasificado"
    assert respuesta.metadata.model_provider == "anthropic"
    assert respuesta.metadata.model_name == AnthropicProvider.default_model
    assert respuesta.metadata.finish_reason == "end_turn"


def test_generate_registra_tokens_y_latencia() -> None:
    """Regla 4: tokens y latencia son campos del Canonical Model, no adorno."""
    provider = AnthropicProvider("llave", client=_client(_anthropic_ok()))

    metadata = provider.generate([Message(role="user", content="x")]).metadata

    assert metadata.usage.input_tokens == 11
    assert metadata.usage.output_tokens == 7
    assert metadata.usage.total_tokens == 18
    assert metadata.latency_ms >= 0


def test_prompt_version_viaja_hasta_la_metadata() -> None:
    """§17: la decisión debe poder decir con qué versión de prompt se produjo."""
    provider = AnthropicProvider("llave", client=_client(_anthropic_ok()))

    metadata = provider.generate(
        [Message(role="user", content="x")],
        prompt_id="product_dna.extract",
        prompt_version="0.1",
    ).metadata

    assert metadata.prompt_id == "product_dna.extract"
    assert metadata.prompt_version == "0.1"


def test_anthropic_manda_el_system_en_su_campo() -> None:
    capturado: list[dict] = []
    provider = AnthropicProvider("llave", client=_client(_anthropic_ok(capture=capturado)))

    provider.generate([Message(role="user", content="hola")], system="eres un analista")

    assert capturado[0]["system"] == "eres un analista"
    assert capturado[0]["messages"] == [{"role": "user", "content": "hola"}]


def test_analyze_image_codifica_en_base64() -> None:
    capturado: list[dict] = []
    provider = AnthropicProvider("llave", client=_client(_anthropic_ok(capture=capturado)))

    provider.analyze_image(b"bytes-de-imagen", "lee la ficha", media_type="image/png")

    bloque = capturado[0]["messages"][0]["content"][0]
    assert bloque["type"] == "image"
    assert bloque["source"]["media_type"] == "image/png"
    assert bloque["source"]["data"] == "Ynl0ZXMtZGUtaW1hZ2Vu"


# ── Errores explícitos (regla 5) ─────────────────────────────────────────────


def test_rate_limit_lanza_excepcion_propia_con_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down", headers={"retry-after": "30"})

    provider = AnthropicProvider("llave", client=_client(handler))

    with pytest.raises(ProviderRateLimitError) as exc:
        provider.generate([Message(role="user", content="x")])

    assert exc.value.retry_after_seconds == 30.0
    assert exc.value.provider == "anthropic"


@pytest.mark.parametrize("codigo", [401, 403])
def test_credencial_rechazada(codigo: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(codigo, text="unauthorized")

    provider = AnthropicProvider("llave-mala", client=_client(handler))

    with pytest.raises(ProviderAuthenticationError):
        provider.generate([Message(role="user", content="x")])


def test_timeout_lanza_provider_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("demasiado lento", request=request)

    provider = AnthropicProvider("llave", client=_client(handler))

    with pytest.raises(ProviderTimeoutError):
        provider.generate([Message(role="user", content="x")])


def test_filtro_de_contenido_no_se_confunde_con_error_generico() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text='{"error":"content blocked by policy"}')

    provider = AnthropicProvider("llave", client=_client(handler))

    with pytest.raises(ContentFilterError):
        provider.generate([Message(role="user", content="x")])


def test_respuesta_sin_content_es_error_no_cadena_vacia() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"inesperado": True})

    provider = AnthropicProvider("llave", client=_client(handler))

    with pytest.raises(ProviderResponseError):
        provider.generate([Message(role="user", content="x")])


def test_proveedor_sin_llave_no_arranca() -> None:
    """Regla 2: queda deshabilitado, y lo dice; no revienta al importar."""
    with pytest.raises(ProviderNotConfiguredError):
        AnthropicProvider("")


# ── Capacidades por proveedor ────────────────────────────────────────────────


def test_anthropic_declara_que_no_hace_embeddings() -> None:
    """§36: sin endpoint real, se dice; no se devuelve un vector inventado."""
    provider = AnthropicProvider("llave", client=_client(_anthropic_ok()))

    with pytest.raises(ProviderCapabilityError):
        provider.embed("motor de 24 voltios")


def test_openai_embed_devuelve_vector() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})

    provider = OpenAIProvider("llave", client=_client(handler))

    assert provider.embed("texto") == [0.1, 0.2, 0.3]


def test_openai_pone_el_system_como_primer_turno() -> None:
    capturado: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturado.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    provider = OpenAIProvider("llave", client=_client(handler))
    provider.generate([Message(role="user", content="hola")], system="eres analista")

    assert capturado[0]["messages"][0] == {"role": "system", "content": "eres analista"}


def test_gemini_traduce_assistant_a_model() -> None:
    """Gemini es el que más se aleja del formato común: la traducción vive en su adaptador."""
    capturado: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturado.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
            },
        )

    provider = GeminiProvider("llave", client=_client(handler))
    provider.generate(
        [
            Message(role="user", content="hola"),
            Message(role="assistant", content="qué tal"),
        ]
    )

    assert [c["role"] for c in capturado[0]["contents"]] == ["user", "model"]


def test_gemini_bloqueo_de_seguridad_es_content_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]})

    provider = GeminiProvider("llave", client=_client(handler))

    with pytest.raises(ContentFilterError):
        provider.generate([Message(role="user", content="x")])


# ── Registro ─────────────────────────────────────────────────────────────────


def test_available_providers_reporta_sin_construir(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "llave-de-prueba")

    from apps.api.config import get_settings

    get_settings.cache_clear()

    estado = available_providers()

    assert estado["anthropic"] is True
    assert estado["openai"] is False
    assert estado["gemini"] is False


def test_build_provider_rechaza_nombre_desconocido() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        build_provider("cohere", api_key="x")


def test_build_provider_sin_llave_falla_explicitamente() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        build_provider("anthropic", api_key="")


# ── temperature opcional ─────────────────────────────────────────────────────


def test_temperature_no_se_manda_si_no_se_pide() -> None:
    """Los modelos recientes la rechazan con HTTP 400; mandarla «por si acaso» rompe."""
    capturado: list[dict] = []
    provider = AnthropicProvider("llave", client=_client(_anthropic_ok(capture=capturado)))

    provider.generate([Message(role="user", content="x")])

    assert "temperature" not in capturado[0]


def test_temperature_se_manda_cuando_se_pide() -> None:
    capturado: list[dict] = []
    provider = AnthropicProvider("llave", client=_client(_anthropic_ok(capture=capturado)))

    provider.generate([Message(role="user", content="x")], temperature=0.7)

    assert capturado[0]["temperature"] == 0.7


def test_openai_omite_temperature_por_defecto() -> None:
    capturado: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturado.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    OpenAIProvider("llave", client=_client(handler)).generate(
        [Message(role="user", content="x")]
    )

    assert "temperature" not in capturado[0]


def test_gemini_omite_temperature_por_defecto() -> None:
    capturado: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturado.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    GeminiProvider("llave", client=_client(handler)).generate(
        [Message(role="user", content="x")]
    )

    assert "temperature" not in capturado[0]["generationConfig"]
