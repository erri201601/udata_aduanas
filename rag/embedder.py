"""Adaptador del proveedor de modelos al puerto `Embedder` (§27, §29).

POR QUÉ EXISTE ESTE ARCHIVO Y NO UNA LLAMADA DIRECTA

El puerto `Embedder` recibe una lista de textos y devuelve una lista de
vectores; `HTTPModelProvider.embed()` recibe UN texto y devuelve UN vector.
La diferencia parece trivial y no lo es: `rag/` no puede depender de la firma
de un proveedor concreto sin romper el §29, y `core/llm/` no puede conocer el
puerto del RAG sin invertir la dependencia. El adaptador es el único sitio
donde las dos formas se tocan. El SDK del proveedor sigue viviendo en
`core/llm/providers/`, que es la regla que no se negocia.

DEGRADA, NUNCA TUMBA A QUIEN LO LLAMA

Ésta es la razón de ser del módulo, más que la conversión de firmas.

Conectar embeddings mueve una llamada de red al camino de una petición de
usuario. Antes, un 429 arruinaba un backfill por lotes que se relanzaba solo;
ahora tumbaría una clasificación en vivo. Eso es inaceptable: **una
clasificación no puede fallar porque no se pudo vectorizar la pregunta**. La
búsqueda por término y vigencia sigue estando ahí, sigue respetando el §14 y
sigue fundamentando — simplemente busca peor.

Por eso `embedder_opcional()` devuelve `None` en vez de propagar, y
`EmbedderDegradable` recuerda si ya falló. Quien lo usa mira `uso_vectores`
para declarar cómo buscó de verdad. Degradar en silencio sería tan malo como
fallar: el resultado saldría peor sin que nadie pudiera saber por qué (Persona
1, 2026-09-09).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from core.llm.errors import ModelProviderError
from core.llm.registry import build_provider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.llm.base import HTTPModelProvider

log = structlog.stdlib.get_logger("rag.embedder")

#: El único proveedor con embeddings de 1536 dimensiones, que es el ancho de
#: `regulatory.legal_chunks.embedding`. Se pide POR NOMBRE, nunca el proveedor
#: por defecto: `DEFAULT_MODEL_PROVIDER` puede ser `anthropic`, que no publica
#: endpoint de embeddings.
PROVEEDOR_DE_EMBEDDINGS: Final = "openai"

#: Cómo se buscó. Lo consume quien presenta el resultado.
MODO_SEMANTICO: Final = "SEMANTICA"
MODO_TERMINO: Final = "TERMINO_Y_VIGENCIA"


class EmbedderDegradable:
    """`Embedder` que se apaga solo al primer fallo, en vez de propagar.

    No reintenta. Con el proveedor caído o sin cuota, reintentar dentro de una
    petición de usuario sólo alarga la espera antes de dar el mismo resultado
    que ya se puede dar sin vectores.

    Tampoco se reactiva dentro de la misma petición: si la primera llamada
    falló, las siguientes de esa consulta usan término. Mezclar pasajes
    recuperados por vector con otros por palabra daría un orden que nadie
    podría explicar.
    """

    def __init__(self, provider: HTTPModelProvider) -> None:
        self._provider = provider
        self._degradado = False
        self._motivo: str | None = None

    @property
    def uso_vectores(self) -> bool:
        """¿Se llegó a vectorizar? `False` si nunca se llamó o si falló."""
        return self._llamado and not self._degradado

    @property
    def motivo_degradacion(self) -> str | None:
        """Por qué se cayó a término. `None` si no se cayó."""
        return self._motivo

    @property
    def modo(self) -> str:
        """Cómo se buscó de verdad, para declararlo en la respuesta."""
        return MODO_SEMANTICO if self.uso_vectores else MODO_TERMINO

    _llamado: bool = False

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Un vector por texto. Lista vacía si no se pudo.

        Devolver `[]` en vez de lanzar es lo que permite que `recuperar()`
        siga adelante: quien recibe una lista vacía busca por término, que es
        exactamente lo que se quiere que pase.
        """
        self._llamado = True
        if self._degradado:
            return []
        try:
            return [self._provider.embed(t) for t in texts]
        except ModelProviderError as exc:
            # Un fallo del proveedor NO es un fallo de la consulta. Se anota,
            # se degrada y se sigue: la búsqueda por término respeta el §14
            # igual y sostiene la misma evidencia.
            self._degradado = True
            self._motivo = f"{type(exc).__name__}: {exc}"
            log.warning(
                "rag.embedder.degradado",
                proveedor=PROVEEDOR_DE_EMBEDDINGS,
                error=type(exc).__name__,
            )
            return []


def embedder_opcional() -> EmbedderDegradable | None:
    """El embedder si hay proveedor configurado; `None` si no.

    `None` no es un error: es «se busca por término». Sin llave, sin cuota o
    con el proveedor mal configurado, la aplicación tiene que seguir
    clasificando y respondiendo consultas — peor, pero funcionando y
    diciéndolo.
    """
    try:
        provider = build_provider(name=PROVEEDOR_DE_EMBEDDINGS)
    except ModelProviderError as exc:
        log.info(
            "rag.embedder.no_disponible",
            proveedor=PROVEEDOR_DE_EMBEDDINGS,
            error=type(exc).__name__,
        )
        return None

    if provider.default_embedding_model is None:
        # No debería pasar pidiendo `openai` por nombre, pero si alguien
        # cambia el proveedor de este módulo, esto lo para antes de que
        # `embed()` lance en mitad de una petición.
        log.warning("rag.embedder.sin_capacidad", proveedor=provider.name)
        return None

    return EmbedderDegradable(provider)
