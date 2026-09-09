"""Puente entre lo recuperado y el contrato de evidencia (§8.1, §49).

Es el cable que faltaba para que una clasificación llegue a ser defendible:
`recuperar()` devuelve chunks, `classify_product()` espera `LegalRef`, y aquí
se convierte lo uno en lo otro.

DOS CAPAS QUE SE REFUERZAN

`recuperar()` ya descarta lo `SYNTHETIC` antes de devolverlo. Esta conversión
lo vuelve a comprobar, y si algo se coló lanza en vez de convertirlo. No es
redundancia por descuido: es la misma decisión que el filtro temporal, que se
aplica en el almacén y otra vez en la recuperación.

La razón es que las dos capas pueden fallar por motivos distintos. La primera
se puede rodear —alguien llama a `a_legal_refs()` con chunks de otro sitio— y
la segunda es la última oportunidad de parar antes de que un texto inventado
se convierta en fundamento jurídico.

Y aun si ésta fallara, el contrato de Persona 1 rechaza el `LEGAL_SOURCE` al
construirlo. Tres capas para la misma cosa, porque el fallo que evitan —una
clasificación «defendible» fundada en ley inventada— es el peor que puede
tener el sistema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.evidence.errors import SyntheticLegalBasisError
from core.evidence.types import DocumentRef, LegalRef

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rag.retrieval import Recuperacion
    from rag.types import LegalChunk


def a_legal_ref(chunk: LegalChunk) -> LegalRef:
    """Convierte un chunk en la referencia que espera el orquestador.

    Lanza `SyntheticLegalBasisError` si el chunk no puede fundamentar. Se
    prefiere lanzar a devolver `None` porque un `None` silencioso acabaría
    filtrado en una comprensión de lista y nadie sabría que se descartó una
    norma — ni por qué.
    """
    if not chunk.puede_fundamentar:
        raise SyntheticLegalBasisError(
            f"{chunk.cita()} tiene data_origin={chunk.data_origin!r} y no puede "
            "sostener una afirmación jurídica (§8.1)"
        )

    return LegalRef(
        document_ref=DocumentRef(
            document=chunk.document,
            article=chunk.article,
            url=chunk.url,
            published_at=chunk.published_at,
            content_hash=chunk.content_hash,
        ),
        valid_from=chunk.valid_from,
        valid_to=chunk.valid_to,
        content_hash=chunk.content_hash,
        data_origin=chunk.data_origin,
        legal_rule_id=chunk.legal_rule_id,
    )


def a_legal_refs(recuperacion: Recuperacion) -> tuple[LegalRef, ...]:
    """Las referencias de una recuperación, listas para `classify_product`.

    Sólo convierte lo que puede fundamentar. Si la recuperación no trae nada
    fundamentable devuelve vacío, y el orquestador marcará la clasificación
    como no defendible — que es lo correcto: sin norma que la sostenga, no lo
    es.
    """
    return tuple(a_legal_ref(c) for c in recuperacion.chunks if c.puede_fundamentar)


def citar(refs: Sequence[LegalRef]) -> tuple[str, ...]:
    """Cómo se leen esas referencias en un dictamen."""
    return tuple(f"{r.document_ref.document}, artículo {r.document_ref.article}" for r in refs)
