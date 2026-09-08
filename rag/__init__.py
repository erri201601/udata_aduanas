"""RAG jurídico — recuperación con fundamento y vigencia (§27).

NUNCA PDF → LLM → RESPUESTA

El pipeline del §27 es:

    normas normalizadas → chunking → metadata → texto + vector
    → recuperación → LLM → respuesta CON evidencia

Saltarse los pasos intermedios produce respuestas que suenan bien y no se
pueden verificar contra ninguna fuente.

USO

    from rag import MemoriaChunkStore, recuperar, trocear

    chunks = trocear(
        texto_del_dof,
        document="Ley Aduanera",
        data_origin="OFFICIAL",
        valid_from=date(1995, 12, 15),
        source_id=fuente_id,
    )
    store = MemoriaChunkStore()
    store.add(chunks)

    resultado = recuperar("¿qué debe transmitir el importador?",
                          on_date=date(2024, 3, 15), store=store)

    resultado.hay_fundamento   # ¿hay con qué responder?
    resultado.citas            # las normas que lo sostienen
    resultado.sin_evidencia()  # el mensaje cuando no hay

DOS REGLAS QUE ESTRUCTURAN EL MÓDULO

**La vigencia va por chunk, no por documento.** El artículo 36-A se reformó
en 2018 y el artículo 1 viene de 1995. Con vigencia por documento, preguntar
qué regía en 2024 devolvería la última versión del texto completo y se citaría
un artículo que ese día no existía. La regla 5 del CLAUDE.md no se puede
cumplir de otro modo.

**`data_origin` va por chunk.** Es lo que impide que un fixture acabe siendo
fundamento jurídico: el Evidence Contract exige `source_id`, `document_ref`,
`valid_from` y `content_hash`, y ninguno mira la procedencia. Un chunk
`SYNTHETIC` no pasa el filtro de `recuperar()` por muy completo que esté.

QUÉ NO HACE ESTA VERSIÓN

No construye evidencia ni la entrega al Evidence Contract. Persona 1 va a
cerrar `core/evidence` para que un origen no fundamentable no pueda colarse;
hasta entonces, este módulo recupera y nada más.

Tampoco persiste: `MemoriaChunkStore` es para desarrollo. El almacén real
sobre pgvector necesita la tabla de chunks que todavía no existe.
"""

from __future__ import annotations

from rag.chunking import trocear
from rag.evidencia import a_legal_ref, a_legal_refs, citar
from rag.memoria import MemoriaChunkStore
from rag.ports import ChunkStore, Embedder
from rag.retrieval import LIMITE_POR_DEFECTO, Recuperacion, recuperar
from rag.types import (
    ORIGENES_QUE_FUNDAMENTAN,
    DataOrigin,
    LegalChunk,
    hash_contenido,
)

__all__ = [
    "LIMITE_POR_DEFECTO",
    "ORIGENES_QUE_FUNDAMENTAN",
    "ChunkStore",
    "DataOrigin",
    "Embedder",
    "LegalChunk",
    "MemoriaChunkStore",
    "Recuperacion",
    "a_legal_ref",
    "a_legal_refs",
    "citar",
    "hash_contenido",
    "recuperar",
    "trocear",
]
