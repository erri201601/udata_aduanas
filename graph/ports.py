"""El puerto del grafo. Quien proyecta no sabe que detrás hay Neo4j (§29).

Tres operaciones y ninguna de lectura de dominio: el proyector escribe, y
quien pregunta al grafo lo hace con Cypher desde fuera. `conteos` existe sólo
para poder DEMOSTRAR la idempotencia, no para consultar el negocio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any


@runtime_checkable
class Grafo(Protocol):
    """Destino de la proyección."""

    def merge_nodos(
        self, etiqueta: str, filas: Sequence[Mapping[str, Any]], *, clave: str = "id"
    ) -> int:
        """Crea o actualiza nodos por `clave`. Devuelve cuántos tocó.

        `MERGE`, nunca `CREATE`: correr la proyección dos veces tiene que dejar
        el mismo grafo, no el doble.
        """
        ...

    def merge_relaciones(
        self,
        tipo: str,
        origen: str,
        destino: str,
        pares: Sequence[tuple[str, str]],
        *,
        clave_origen: str = "id",
        clave_destino: str = "id",
    ) -> int:
        """Crea o actualiza relaciones entre nodos que YA existen.

        Las claves son por extremo porque no todo nodo se identifica igual:
        `Country` no sale de ninguna tabla y su identidad es el código.

        Sin propiedades a propósito: ninguna relación tiene vigencia propia
        distinta de la de sus extremos, y dos copias de la misma verdad se
        desincronizan (Persona 1, 21-sep).
        """
        ...

    def conteos(self) -> dict[str, int]:
        """Cuántos nodos hay por etiqueta y cuántas relaciones por tipo."""
        ...
