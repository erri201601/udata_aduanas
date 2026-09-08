"""Puertos del RAG: lo que necesita del exterior.

Mismo criterio que el RGI Engine y el Product DNA Engine. El pipeline no sabe
qué modelo calcula los vectores ni dónde se guardan los chunks: lo declara y
alguien se lo inyecta.

Eso permite construirlo y probarlo HOY, sin corpus cargado y sin pgvector, y
de paso fija el contrato al revés: al declarar qué necesita el RAG de un
almacén de chunks, queda escrito qué forma deben tener las normas al cargarse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from rag.types import LegalChunk


@runtime_checkable
class Embedder(Protocol):
    """Convierte texto en vector.

    Se declara aparte de `ModelProvider` porque no todo embedder es un LLM:
    puede ser un modelo local, y el §29 sólo exige que el dominio no sepa cuál.
    """

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Un vector por texto, en el mismo orden."""
        ...


@runtime_checkable
class ChunkStore(Protocol):
    """Almacén de chunks con búsqueda.

    `on_date` es OBLIGATORIO en la recuperación y no tiene valor por defecto.
    Es lo que impide devolver una norma que no regía: si fuera opcional,
    cualquier consulta que lo olvidara recuperaría el texto vigente hoy para
    una operación de hace dos años, y la cita parecería correcta.
    """

    def add(self, chunks: Sequence[LegalChunk]) -> int:
        """Indexa. Devuelve cuántos entraron."""
        ...

    def search(
        self,
        *,
        on_date: date,
        query_embedding: Sequence[float] | None = None,
        terms: Sequence[str] = (),
        limit: int = 10,
        solo_fundamentables: bool = True,
    ) -> Sequence[LegalChunk]:
        """Chunks vigentes en la fecha que coinciden con la consulta.

        `solo_fundamentables` en `True` por defecto: quien quiera chunks de
        prueba tiene que pedirlos explícitamente, y así el camino cómodo es
        también el seguro.
        """
        ...
