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

from core.classification import classify_product
from database.repositories.chunks import PostgresChunkStore
from database.repositories.notes import LegalNotesRepository
from database.repositories.tariff import TariffCatalogRepository
from rag import a_legal_refs, embedder_opcional, recuperar

from apps.api.dna import terminos

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from core.classification import ClassificationOutcome
    from core.evidence.types import LegalRef
    from core.product_dna.types import ProductDnaDraft
    from rag import EmbedderDegradable
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
    legal_refs = a_legal_refs(recuperacion)

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
