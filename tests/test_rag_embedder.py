"""Tests del adaptador de embeddings (§27, §29).

LO QUE ESTOS TESTS PROTEGEN

Conectar embeddings mueve una llamada de red al camino de una petición de
usuario. Antes, un 429 arruinaba un backfill por lotes que se relanzaba solo;
ahora tumbaría una clasificación en vivo. La exigencia de Persona 1 (9 de
septiembre) es explícita: **si el proveedor falla, se degrada a búsqueda por
término y se dice; nunca se falla la clasificación**.

Estos tests fijan las dos mitades: que degrada, y que lo declara. Degradar en
silencio sería tan malo como fallar.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from core.llm.errors import (
    ModelProviderError,
    ProviderNotConfiguredError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from rag.embedder import (
    MODO_SEMANTICO,
    MODO_TERMINO,
    EmbedderDegradable,
    embedder_opcional,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

VECTOR = [0.1] * 1536


class ProveedorQueResponde:
    name = "openai"
    default_embedding_model = "text-embedding-3-small"

    def __init__(self) -> None:
        self.llamadas: list[str] = []

    def embed(self, text: str, *, model: str | None = None) -> list[float]:
        self.llamadas.append(text)
        return VECTOR


class ProveedorQueFalla(ProveedorQueResponde):
    def __init__(self, error: ModelProviderError) -> None:
        super().__init__()
        self._error = error

    def embed(self, text: str, *, model: str | None = None) -> list[float]:
        self.llamadas.append(text)
        raise self._error


def test_con_proveedor_sano_devuelve_vectores() -> None:
    e = EmbedderDegradable(ProveedorQueResponde())  # type: ignore[arg-type]

    assert e.embed(["hola"]) == [VECTOR]
    assert e.uso_vectores is True
    assert e.modo == MODO_SEMANTICO
    assert e.motivo_degradacion is None


@pytest.mark.parametrize(
    "error",
    [
        ProviderResponseError("429 Too Many Requests", provider="openai"),
        ProviderTimeoutError("sin respuesta en 30s", provider="openai"),
    ],
)
def test_un_fallo_del_proveedor_no_se_propaga(error: ModelProviderError) -> None:
    """EL TEST QUE IMPORTA.

    Un 429 no puede tumbar una clasificación en vivo. Se devuelve vacío, que
    es como `recuperar` sabe que tiene que seguir por término.
    """
    e = EmbedderDegradable(ProveedorQueFalla(error))  # type: ignore[arg-type]

    assert e.embed(["hola"]) == []
    assert e.uso_vectores is False
    assert e.modo == MODO_TERMINO


def test_el_motivo_de_la_degradacion_queda_registrado() -> None:
    """Degradar en silencio sería tan malo como fallar."""
    e = EmbedderDegradable(  # type: ignore[arg-type]
        ProveedorQueFalla(ProviderResponseError("429 Too Many Requests", provider="openai"))
    )
    e.embed(["hola"])

    assert e.motivo_degradacion is not None
    assert "ProviderResponseError" in e.motivo_degradacion
    assert "429" in e.motivo_degradacion


def test_no_reintenta_dentro_de_la_misma_peticion() -> None:
    """Con el proveedor caído, reintentar sólo alarga la espera.

    Y mezclar pasajes recuperados por vector con otros por palabra daría un
    orden que nadie podría explicar.
    """
    proveedor = ProveedorQueFalla(ProviderTimeoutError("timeout", provider="openai"))
    e = EmbedderDegradable(proveedor)  # type: ignore[arg-type]

    e.embed(["primera"])
    e.embed(["segunda"])

    assert proveedor.llamadas == ["primera"], "la segunda no debió llegar al proveedor"


def test_sin_llamar_todavia_no_se_afirma_que_uso_vectores() -> None:
    """`uso_vectores` describe lo que pasó, no lo que se podría hacer."""
    e = EmbedderDegradable(ProveedorQueResponde())  # type: ignore[arg-type]

    assert e.uso_vectores is False
    assert e.modo == MODO_TERMINO


def test_sin_proveedor_configurado_devuelve_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin llave la aplicación sigue clasificando. `None` no es un error."""

    def _falla(**_kwargs: Any) -> Any:
        raise ProviderNotConfiguredError("sin llave", provider="openai")

    monkeypatch.setattr("rag.embedder.build_provider", _falla)

    assert embedder_opcional() is None


def test_un_proveedor_sin_embeddings_se_rechaza(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic no publica endpoint de embeddings; se para antes de llamar."""

    class SinEmbeddings:
        name = "anthropic"
        default_embedding_model = None

    monkeypatch.setattr("rag.embedder.build_provider", lambda **_k: SinEmbeddings())

    assert embedder_opcional() is None


def test_se_pide_openai_por_nombre_nunca_el_proveedor_por_defecto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DEFAULT_MODEL_PROVIDER` puede ser `anthropic`, que no vectoriza."""
    capturado: dict[str, Any] = {}

    def _espia(**kwargs: Any) -> Any:
        capturado.update(kwargs)
        return ProveedorQueResponde()

    monkeypatch.setattr("rag.embedder.build_provider", _espia)
    embedder_opcional()

    assert capturado["name"] == "openai"


# ── La integración con `recuperar` ───────────────────────────────────────────


class AlmacenEspia:
    """Registra si le llegó un vector o no."""

    def __init__(self) -> None:
        self.recibio_vector: bool | None = None

    def search(
        self,
        *,
        on_date: date,
        query_embedding: Sequence[float] | None = None,
        terms: Sequence[str] = (),
        limit: int = 10,
        solo_fundamentables: bool = True,
    ) -> Sequence[Any]:
        self.recibio_vector = query_embedding is not None
        return []


def test_un_embedder_degradado_hace_que_se_busque_por_termino() -> None:
    """Sin esto, `recuperar` reventaría con IndexError sobre la lista vacía.

    Es la degradación prevista convertida en fallo dentro de una petición de
    usuario: exactamente lo que este diseño existe para impedir.
    """
    from rag import recuperar

    almacen = AlmacenEspia()
    e = EmbedderDegradable(  # type: ignore[arg-type]
        ProveedorQueFalla(ProviderResponseError("429", provider="openai"))
    )

    recuperar("valor en aduana", on_date=date(2024, 3, 15), store=almacen, embedder=e)  # type: ignore[arg-type]

    assert almacen.recibio_vector is False, "debió buscar por término"


def test_con_embedder_sano_se_busca_por_vector() -> None:
    from rag import recuperar

    almacen = AlmacenEspia()
    e = EmbedderDegradable(ProveedorQueResponde())  # type: ignore[arg-type]

    recuperar("valor en aduana", on_date=date(2024, 3, 15), store=almacen, embedder=e)  # type: ignore[arg-type]

    assert almacen.recibio_vector is True
