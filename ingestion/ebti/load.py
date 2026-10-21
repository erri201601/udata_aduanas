"""PARSED → DATABASE de las BTI (ADR 0020). Misma tabla que CBP."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from database.models import ComparableRuling

from ingestion.ebti.ebti import AUTORIDAD

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ingestion.ebti.ebti import ParsedBti


def cargar(
    session: Session,
    bti: ParsedBti,
    *,
    content_hash: str,
    minio_key: str,
    retrieved_at: datetime | None = None,
) -> bool:
    """Inserta la BTI o actualiza su estado. Devuelve si era nueva.

    Una BTI vuelve a aparecer en una diaria posterior cuando se invalida: lo
    que cambia es su estado y el fin de su vigencia. El resto se emitió y no
    cambia.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    existente = session.scalars(
        sa.select(ComparableRuling).where(
            ComparableRuling.authority == AUTORIDAD,
            ComparableRuling.ruling_number == bti.referencia,
        )
    ).one_or_none()
    documento = f"EBTI {bti.pais} {bti.referencia} ({minio_key})"
    if existente is not None:
        existente.is_revoked = not bti.valida
        existente.valid_to = bti.hasta
        existente.categories = bti.categorias
        existente.content_hash = content_hash
        existente.source_document = documento
        existente.retrieved_at = retrieved_at
        return False
    session.add(
        ComparableRuling(
            authority=AUTORIDAD,
            ruling_number=bti.referencia,
            collection=bti.pais,
            ruling_date=bti.emitida,
            subject=bti.asunto,
            categories=bti.categorias,
            tariff_codes=[bti.codigo_nc],
            hs6_codes=[bti.hs6] if bti.hs6 else [],
            full_text=bti.texto,
            is_revoked=not bti.valida,
            # Una BTI tiene vigencia propia (normalmente tres años): aquí sí
            # hay `valid_to`, a diferencia de una resolución de CBP.
            data_origin="PUBLIC",
            valid_from=bti.desde,
            valid_to=bti.hasta,
            published_at=bti.emitida,
            source_url=bti.url,
            source_document=documento,
            content_hash=content_hash,
            retrieved_at=retrieved_at,
        )
    )
    return True
