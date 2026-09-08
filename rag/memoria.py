"""Almacén de chunks en memoria.

Implementa `ChunkStore` sin PostgreSQL ni pgvector. Existe para dos cosas:
probar el pipeline entero hoy, y servir de referencia ejecutable de lo que
tendrá que hacer el almacén real — incluido el filtro temporal, que es la
parte que más fácil se olvida al escribir SQL.

NO es el almacén de producción. Recorre la lista entera en cada búsqueda y
compara por coseno a mano: con la Ley Aduanera completa sería inaceptable.
Para eso está pgvector con su índice.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from rag.types import LegalChunk


def _coseno(a: Sequence[float], b: Sequence[float]) -> float:
    """Similitud coseno. Cero si algún vector es nulo, en vez de dividir por cero."""
    if len(a) != len(b):
        return 0.0
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


class MemoriaChunkStore:
    """`ChunkStore` en memoria, para pruebas y desarrollo."""

    def __init__(self) -> None:
        self._chunks: list[LegalChunk] = []

    def add(self, chunks: Sequence[LegalChunk]) -> int:
        self._chunks.extend(chunks)
        return len(chunks)

    def search(
        self,
        *,
        on_date: date,
        query_embedding: Sequence[float] | None = None,
        terms: Sequence[str] = (),
        limit: int = 10,
        solo_fundamentables: bool = True,
    ) -> Sequence[LegalChunk]:
        """Vigentes en la fecha, ordenados por parecido.

        El filtro temporal va PRIMERO, antes de puntuar: puntuar y filtrar
        después haría que una norma no vigente ocupara un puesto del límite y
        desplazara a una que sí regía.
        """
        candidatos = [c for c in self._chunks if c.vigente_en(on_date)]
        if solo_fundamentables:
            candidatos = [c for c in candidatos if c.puede_fundamentar]

        def puntuar(chunk: LegalChunk) -> float:
            if query_embedding is not None and chunk.embedding is not None:
                return _coseno(query_embedding, chunk.embedding)
            texto = chunk.text.lower()
            return sum(1.0 for t in terms if t in texto)

        return sorted(candidatos, key=puntuar, reverse=True)[:limit]

    def __len__(self) -> int:
        return len(self._chunks)
