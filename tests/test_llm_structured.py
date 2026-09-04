"""Salida estructurada: validación y reintentos (regla 3 de TAREA_P3).

`generate_structured` nunca debe devolver JSON sin validar. Estos tests fijan
ese contrato, incluido el caso en que el modelo nunca acierta.
"""

from __future__ import annotations

import json

import httpx
import pytest
from core.llm import StructuredOutputError
from core.llm.providers import AnthropicProvider
from core.llm.structured import extract_json, validate_payload
from core.llm.types import Message
from pydantic import BaseModel, Field, ValidationError


class Ficha(BaseModel):
    """Esquema mínimo para los tests."""

    product_name: str
    voltage: str
    confidence: float = Field(ge=0.0, le=1.0)


def _provider_que_responde(*respuestas: str) -> AnthropicProvider:
    """Proveedor que devuelve las respuestas dadas, una por llamada."""
    pendientes = list(respuestas)

    def handler(request: httpx.Request) -> httpx.Response:
        texto = pendientes.pop(0) if pendientes else "{}"
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": texto}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "stop_reason": "end_turn",
            },
        )

    return AnthropicProvider("llave", client=httpx.Client(transport=httpx.MockTransport(handler)))


VALIDO = json.dumps({"product_name": "Motor", "voltage": "24 V", "confidence": 0.9})


# ── Extracción del JSON ──────────────────────────────────────────────────────


def test_extract_json_atraviesa_la_valla_de_codigo() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_ignora_la_prosa_de_alrededor() -> None:
    assert extract_json('Claro, aquí tienes:\n{"a": 1}\nEspero que sirva.') == '{"a": 1}'


def test_extract_json_acepta_json_pelado() -> None:
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_json_malformado_es_error_de_validacion() -> None:
    with pytest.raises(ValidationError):
        validate_payload("{no es json", Ficha)


# ── Contrato de generate_structured ──────────────────────────────────────────


def test_devuelve_el_modelo_ya_validado() -> None:
    provider = _provider_que_responde(VALIDO)

    respuesta = provider.generate_structured([Message(role="user", content="x")], Ficha)

    assert isinstance(respuesta.data, Ficha)
    assert respuesta.data.product_name == "Motor"
    assert respuesta.metadata.attempts == 1


def test_reintenta_cuando_la_salida_no_valida() -> None:
    """El segundo intento recibe el error como pista y acierta."""
    provider = _provider_que_responde('{"product_name": "Motor"}', VALIDO)

    respuesta = provider.generate_structured([Message(role="user", content="x")], Ficha)

    assert respuesta.data.voltage == "24 V"
    assert respuesta.metadata.attempts == 2


def test_los_tokens_de_los_reintentos_se_acumulan() -> None:
    """Un reintento cuesta dinero: si no se suma, el coste real queda oculto."""
    provider = _provider_que_responde("basura", VALIDO)

    metadata = provider.generate_structured([Message(role="user", content="x")], Ficha).metadata

    assert metadata.usage.input_tokens == 20
    assert metadata.usage.output_tokens == 10


def test_agotar_intentos_conserva_la_salida_cruda() -> None:
    provider = _provider_que_responde("nada", "tampoco", "sigue mal")

    with pytest.raises(StructuredOutputError) as exc:
        provider.generate_structured([Message(role="user", content="x")], Ficha, max_attempts=3)

    assert exc.value.attempts == 3
    assert exc.value.raw_output == "sigue mal"
    assert exc.value.validation_error


def test_un_valor_fuera_de_rango_no_pasa() -> None:
    """El esquema no es decorativo: confidence > 1 se rechaza."""
    fuera = json.dumps({"product_name": "M", "voltage": "24 V", "confidence": 7.0})
    provider = _provider_que_responde(fuera, fuera)

    with pytest.raises(StructuredOutputError):
        provider.generate_structured([Message(role="user", content="x")], Ficha, max_attempts=2)


def test_max_attempts_invalido_se_rechaza() -> None:
    provider = _provider_que_responde(VALIDO)

    with pytest.raises(ValueError, match="max_attempts"):
        provider.generate_structured([Message(role="user", content="x")], Ficha, max_attempts=0)


def test_el_esquema_se_inyecta_en_el_system_prompt() -> None:
    capturado: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturado.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": VALIDO}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    provider = AnthropicProvider(
        "llave", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    provider.generate_structured([Message(role="user", content="x")], Ficha)

    assert "product_name" in capturado[0]["system"]
