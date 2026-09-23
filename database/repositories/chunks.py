"""`ChunkStore` real sobre `regulatory.legal_chunks` (pgvector), §27 / PR #45.

`rag/__init__.py` lo dice explícito: `MemoriaChunkStore` es sólo para
desarrollo, y "el almacén real sobre pgvector necesita la tabla de chunks que
todavía no existe". Esta clase es esa tabla puesta a disposición del puerto
`ChunkStore` (`rag.ports`) para que `rag.retrieval.recuperar()` funcione igual
apunte a memoria o a Postgres.

DOS FILTROS, EN ESE ORDEN

1. Vigencia (`valid_from`/`valid_to`) — regla 5 CLAUDE.md. Va en el WHERE,
   antes de puntuar: es exactamente lo que pide `ix_legal_chunks_vigencia`.
2. Procedencia (`solo_fundamentables`) — un chunk `SYNTHETIC` no puede
   sostener una afirmación jurídica por muy completo que esté.

`add()` inserta usando la fila real de `LegalRule`/`LegalDocument`: exige
`chunk.document_id` (a qué documento pertenece) y `chunk.url` (su
`source_url`), porque `RegulatoryMixin` no permite NULL ahí para ningún otro
dato normativo de este sistema y un chunk no es la excepción — inventar un
valor sería peor que rechazarlo. `retrieved_at` no está en el contrato de
`LegalChunk` (es metadato de cuándo SE INDEXÓ, no de la norma en sí), así que
se toma como el momento de este `add()`.

`legal_rule_id` SE RESUELVE SOLO, POR LA TERNA

`add()` busca en `legal_rules` por `(legal_document_id, rule_number, valid_from)`
—la misma terna del `UniqueConstraint` de esa tabla, así que el cruce es
1 a 1— y liga el chunk a la fila que encuentra (decisión de Persona 1,
2026-09-09: sin esto, el panel de impacto no puede cruzar lo que cita el RAG
con `classification_decisions.legal_rule_ids`). Nunca por `(documento,
artículo)` solo: eso sólo funciona mientras exista una única versión
cargada de cada artículo, y este sistema entero está construido sobre
vigencia por chunk. Si no hay match, `legal_rule_id` queda `NULL` y se
registra un `warning` — es un dato que hay que mirar, no un hueco que se
rellena en silencio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from rag.types import ORIGENES_QUE_FUNDAMENTAN, LegalChunk

from database.models import LegalChunkRecord, LegalDocument, LegalRule

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.orm import Session

log = structlog.stdlib.get_logger("database.repositories.chunks")


class ChunkPersistError(ValueError):
    """Un `LegalChunk` no trae lo mínimo para poder guardarse (§1/§3 CLAUDE.md)."""


def _vigentes(on_date: date) -> sa.ColumnElement[bool]:
    """Misma regla temporal que `TariffCatalogRepository`/`LegalNotesRepository` (§14)."""
    return sa.and_(
        LegalChunkRecord.valid_from <= on_date,
        sa.or_(LegalChunkRecord.valid_to.is_(None), LegalChunkRecord.valid_to >= on_date),
    )


def _row_to_chunk(
    row: LegalChunkRecord, *, document: str, distancia: float | None = None
) -> LegalChunk:
    return LegalChunk(
        distancia=distancia,
        source_id=row.source_id,
        document_id=row.legal_document_id,
        legal_rule_id=row.legal_rule_id,
        document=document,
        article=row.article,
        path=row.path,
        text=row.text,
        heading=row.heading,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        data_origin=row.data_origin,  # type: ignore[arg-type]
        content_hash=row.content_hash,
        published_at=row.published_at,
        url=row.source_url,
        embedding=list(row.embedding) if row.embedding is not None else None,
    )


class PostgresChunkStore:
    """`ChunkStore` (`rag.ports`) respaldado por `regulatory.legal_chunks`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, chunks: Sequence[LegalChunk]) -> int:
        """Inserta. Devuelve cuántos entraron.

        Recarga el mismo documento/artículo/vigencia: lo rechaza el
        `UniqueConstraint` de la tabla (`uq_legal_chunks_document_article_valid_from`),
        igual que en `legal_rules` — sin eso, una recarga duplicaría en silencio.
        """
        ahora = datetime.now(UTC)
        filas = [self._to_row(chunk, retrieved_at=ahora) for chunk in chunks]
        self._session.add_all(filas)
        self._session.flush()
        log.info("chunks.add", n=len(filas))
        return len(filas)

    def _to_row(self, chunk: LegalChunk, *, retrieved_at: datetime) -> LegalChunkRecord:
        if chunk.document_id is None:
            raise ChunkPersistError(
                f"chunk {chunk.article!r} sin document_id: no se puede guardar "
                "sin saber a qué legal_document pertenece."
            )
        if chunk.url is None:
            raise ChunkPersistError(
                f"chunk {chunk.article!r} sin url: regulatory.legal_chunks exige "
                "source_url, igual que el resto del dato normativo (§1 CLAUDE.md)."
            )
        legal_rule_id = self._session.scalar(
            sa.select(LegalRule.id).where(
                LegalRule.legal_document_id == chunk.document_id,
                LegalRule.rule_number == chunk.article,
                LegalRule.valid_from == chunk.valid_from,
            )
        )
        if legal_rule_id is None:
            log.warning(
                "chunks.sin_norma_detras",
                article=chunk.article,
                document_id=str(chunk.document_id),
                valid_from=chunk.valid_from.isoformat(),
            )
        return LegalChunkRecord(
            legal_document_id=chunk.document_id,
            legal_rule_id=legal_rule_id,
            source_id=chunk.source_id,
            article=chunk.article,
            path=chunk.path,
            heading=chunk.heading,
            text=chunk.text,
            embedding=chunk.embedding,
            data_origin=chunk.data_origin,
            valid_from=chunk.valid_from,
            valid_to=chunk.valid_to,
            published_at=chunk.published_at,
            source_url=chunk.url,
            content_hash=chunk.content_hash,
            retrieved_at=retrieved_at,
        )

    def search(
        self,
        *,
        on_date: date,
        query_embedding: Sequence[float] | None = None,
        terms: Sequence[str] = (),
        limit: int = 10,
        solo_fundamentables: bool = True,
    ) -> Sequence[LegalChunk]:
        condiciones = [_vigentes(on_date)]
        if solo_fundamentables:
            condiciones.append(LegalChunkRecord.data_origin.in_(ORIGENES_QUE_FUNDAMENTAN))

        # La distancia se SELECCIONA, no sólo se ordena por ella. Antes se
        # calculaba para el ORDER BY y se tiraba, así que el llamante recibía
        # ocho pasajes sin manera de saber si el primero se parecía mucho o
        # poco a la pregunta.
        distancia: sa.ColumnElement[float] | sa.Null = sa.null()
        if query_embedding is not None:
            distancia = LegalChunkRecord.embedding.cosine_distance(list(query_embedding))

        consulta = (
            sa.select(LegalChunkRecord, LegalDocument.title, distancia.label("distancia"))
            .join(LegalDocument, LegalChunkRecord.legal_document_id == LegalDocument.id)
            .where(*condiciones)
        )

        if query_embedding is not None:
            # Sin vector no hay con qué rankear por coseno: sólo entran las
            # filas ya vectorizadas. El resto de la vigencia no se pierde: una
            # búsqueda por término aparte las sigue encontrando.
            consulta = consulta.where(LegalChunkRecord.embedding.is_not(None)).order_by(
                sa.text("distancia")
            )
        else:
            if terms:
                consulta = consulta.where(
                    sa.or_(*(LegalChunkRecord.text.ilike(f"%{t}%") for t in terms))
                )
            # Sin vector con qué ordenar por parecido, lo más vigente primero
            # es el desempate menos arbitrario.
            consulta = consulta.order_by(LegalChunkRecord.valid_from.desc())

        filas = self._session.execute(consulta.limit(limit)).all()
        return [_row_to_chunk(fila, document=titulo, distancia=d) for fila, titulo, d in filas]
