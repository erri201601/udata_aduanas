"""Tests del mapeo al Canonical Model.

Fijan el contrato acordado con Persona 2 (opción A). Si alguien renombra un
campo de un lado, estos tests fallan antes que la escritura en base.
"""

from __future__ import annotations

import pytest
from core.llm.canonical import CanonicalAIFields, to_canonical_fields
from core.llm.types import CallMetadata, Usage

pytestmark = pytest.mark.unit

# El acuerdo, escrito una sola vez. Es la fuente de verdad del test.
CAMPOS_ACORDADOS = frozenset(
    {
        "model_provider",
        "model_name",
        "prompt_id",
        "prompt_version",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "attempts",
        "finish_reason",
    }
)


def _metadata(**cambios: object) -> CallMetadata:
    base = {
        "model_provider": "anthropic",
        "model_name": "claude-opus-5",
        "prompt_id": "product_dna/extract",
        "prompt_version": "0.1",
        "usage": Usage(input_tokens=1200, output_tokens=340),
        "latency_ms": 1875,
        "attempts": 1,
        "finish_reason": "stop",
    }
    return CallMetadata(**(base | cambios))  # type: ignore[arg-type]


def test_devuelve_exactamente_los_campos_acordados() -> None:
    """Ni uno más ni uno menos: un campo extra rompería el `**` al construir."""
    campos = to_canonical_fields(_metadata())

    assert set(campos) == CAMPOS_ACORDADOS


def test_los_valores_se_mapean_sin_traduccion() -> None:
    campos = to_canonical_fields(_metadata())

    assert campos["model_provider"] == "anthropic"
    assert campos["model_name"] == "claude-opus-5"
    assert campos["prompt_id"] == "product_dna/extract"
    assert campos["prompt_version"] == "0.1"
    assert campos["input_tokens"] == 1200
    assert campos["output_tokens"] == 340
    assert campos["latency_ms"] == 1875
    assert campos["attempts"] == 1
    assert campos["finish_reason"] == "stop"


def test_total_tokens_no_se_persiste() -> None:
    """Es derivable de input + output; duplicarlo permite que discrepen."""
    campos = to_canonical_fields(_metadata())

    assert "total_tokens" not in campos
    assert campos["input_tokens"] + campos["output_tokens"] == 1540


def test_called_at_no_se_persiste() -> None:
    """`TimestampMixin` ya registra cuándo se creó la fila (decisión 4)."""
    assert "called_at" not in to_canonical_fields(_metadata())


@pytest.mark.parametrize("campo", ["confidence", "requires_human_review"])
def test_no_inventa_campos_de_otro_modulo(campo: str) -> None:
    """Esta capa no infiere confianza: eso es del motor de clasificación."""
    assert campo not in to_canonical_fields(_metadata())


def test_el_agregado_de_los_reintentos_llega_completo() -> None:
    """Tras reintentar, tokens y latencia vienen sumados y `attempts` lo dice.

    Es la razón de que estos campos vivan en la fila de decisión y no en una
    tabla por llamada: lo que se persiste es el costo total de la decisión.
    """
    campos = to_canonical_fields(
        _metadata(
            usage=Usage(input_tokens=3600, output_tokens=1020),
            latency_ms=5625,
            attempts=3,
        )
    )

    assert campos["attempts"] == 3
    assert campos["input_tokens"] == 3600
    assert campos["latency_ms"] == 5625


def test_los_opcionales_viajan_como_none() -> None:
    """Un proveedor puede no reportar `finish_reason`; no se inventa un valor."""
    campos = to_canonical_fields(
        _metadata(prompt_id=None, prompt_version=None, finish_reason=None)
    )

    assert campos["prompt_id"] is None
    assert campos["prompt_version"] is None
    assert campos["finish_reason"] is None


def test_los_nombres_son_neutros_entre_proveedores() -> None:
    """El Canonical Model no puede casarse con la nomenclatura de OpenAI (§29)."""
    campos = to_canonical_fields(_metadata())

    assert "prompt_tokens" not in campos
    assert "completion_tokens" not in campos


def test_el_typeddict_declara_los_mismos_campos() -> None:
    """El tipo y el acuerdo no pueden divergir sin que alguien lo note."""
    assert set(CanonicalAIFields.__annotations__) == CAMPOS_ACORDADOS
