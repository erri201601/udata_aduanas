"""La tubería de clasificación, sin persistir: DNA → normas → motor.

Existe como función aparte por una razón: el harness de `hs_accuracy` tiene que
medir EXACTAMENTE el camino que usa `POST /products/{id}/classify`. Si el
harness copiara la tubería, el día que alguien cambie la consulta jurídica o el
embedder en el router, el número seguiría midiendo la versión vieja sin que
nadie lo notara.

No escribe nada. Quien quiera guardar el resultado —el router— llama después a
`save_classification`. El harness no lo hace nunca.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from core.classification import classify_product, fundamenta_clasificacion
from database.models import LegalDocument
from database.repositories.chunks import PostgresChunkStore
from database.repositories.notes import LegalNotesRepository
from database.repositories.tariff import TariffCatalogRepository
from rag import a_legal_refs, embedder_opcional, recuperar

from apps.api.dna import terminos

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import date

    from core.classification import ClassificationOutcome
    from core.evidence.types import LegalRef
    from core.product_dna.types import ProductDnaDraft
    from rag import EmbedderDegradable
    from rag.retrieval import Recuperacion
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Clasificado:
    """El resultado del motor y lo que hace falta para declararlo."""

    outcome: ClassificationOutcome
    legal_refs: tuple[LegalRef, ...]
    hay_notas: bool
    embedder: EmbedderDegradable | None
    consulta_juridica: str

    @property
    def uso_vectores(self) -> bool:
        return self.embedder is not None and self.embedder.uso_vectores


def clasificar_borrador(
    session: Session,
    borrador: ProductDnaDraft,
    *,
    operation_date: date,
    trade_flow: str,
    search_terms: Sequence[str] | None = None,
) -> Clasificado:
    """Clasifica un Product DNA con el corpus vigente en `operation_date` (§14).

    Si el proveedor de vectores no está o falla, `embedder_opcional` lo absorbe
    y se sigue por término y vigencia. Clasificar es lo que no puede dejar de
    ocurrir; buscar por significado es lo que lo hace mejor.
    """
    # Import diferido: el router importa este módulo, y la consulta jurídica
    # vive en el router desde el PR #54.
    from apps.api.routers.products import _consulta_juridica

    notas = LegalNotesRepository(session)
    busqueda = list(search_terms) if search_terms else terminos(borrador)
    consulta = _consulta_juridica(busqueda)

    embedder = embedder_opcional()
    recuperacion = recuperar(
        consulta,
        on_date=operation_date,
        store=PostgresChunkStore(session),
        embedder=embedder,
    )
    legal_refs = a_legal_refs(_solo_lo_que_funda_una_clasificacion(session, recuperacion))

    outcome = classify_product(
        borrador,
        operation_date=operation_date,
        catalog=TariffCatalogRepository(session),
        notes=notas,
        search_terms=busqueda,
        legal_refs=legal_refs,
        trade_flow=trade_flow,
    )
    return Clasificado(
        outcome=outcome,
        legal_refs=legal_refs,
        hay_notas=notas.hay_corpus(on_date=operation_date),
        embedder=embedder,
        consulta_juridica=consulta,
    )


def _solo_lo_que_funda_una_clasificacion(
    session: Session, recuperacion: Recuperacion
) -> Recuperacion:
    """Descarta lo recuperado que no puede fundamentar una CLASIFICACIÓN.

    `a_legal_refs` ya filtra por procedencia —lo sintético no fundamenta— pero
    eso es una dimensión distinta de ésta. El artículo 78 de la Ley Aduanera es
    oficial, vigente y verificable, y aun así no sustenta dónde clasifica una
    mercancía: habla de cómo determinar el valor en aduana.

    El filtro va aquí y no dentro del RAG a propósito: recuperar sigue
    devolviendo todo lo que rige ese día, porque el Copilot y el Sentinel sí
    quieren la Ley Aduanera. Lo que cambia es qué se le entrega al motor como
    fundamento de esta decisión concreta.

    Un documento cuyo tipo no se puede resolver NO pasa: no se presume
    fundamento lo que no se pudo comprobar.
    """
    if not recuperacion.chunks:
        return recuperacion

    ids = {c.document_id for c in recuperacion.chunks if c.document_id}
    tipos: dict[uuid.UUID, str] = {
        fila.id: fila.kind
        for fila in session.execute(
            sa.select(LegalDocument.id, LegalDocument.kind).where(LegalDocument.id.in_(ids))
        )
    }
    fundamentables = tuple(
        c
        for c in recuperacion.chunks
        # Sin `document_id` no hay forma de saber de qué instrumento sale, y lo
        # que no se puede comprobar no se presume fundamento.
        if c.document_id is not None and fundamenta_clasificacion(tipos.get(c.document_id))
    )
    return recuperacion.model_copy(update={"chunks": fundamentables})
