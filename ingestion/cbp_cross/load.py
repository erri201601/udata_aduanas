"""PARSED → DATABASE de las resoluciones de CBP (ADR 0019)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from database.models import ComparableRuling

from ingestion.cbp_cross.cross import AUTORIDAD

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ingestion.cbp_cross.cross import ParsedRuling

log = structlog.stdlib.get_logger("ingestion.cbp_cross.load")


def cargar(
    session: Session,
    resolucion: ParsedRuling,
    *,
    content_hash: str,
    minio_key: str,
    retrieved_at: datetime | None = None,
) -> bool:
    """Inserta la resolución o actualiza su estado. Devuelve si era nueva.

    Una resolución ya cargada sólo cambia en lo que CBP puede cambiar después:
    que la revoquen, la modifiquen o se relacione con otras. El texto de una
    resolución emitida no cambia; si el RAW nuevo trae otro hash, se registra
    el nuevo para que la fila apunte a lo último que se leyó.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    existente = session.scalars(
        sa.select(ComparableRuling).where(
            ComparableRuling.authority == AUTORIDAD,
            ComparableRuling.ruling_number == resolucion.ruling_number,
        )
    ).one_or_none()
    if existente is not None:
        existente.is_revoked = resolucion.is_revoked
        existente.revoked_by = list(resolucion.revoked_by)
        existente.modified_by = list(resolucion.modified_by)
        existente.related_rulings = list(resolucion.related_rulings)
        if existente.content_hash != content_hash:
            existente.content_hash = content_hash
            existente.source_document = _documento(resolucion, minio_key)
            existente.retrieved_at = retrieved_at
        return False
    session.add(
        ComparableRuling(
            authority=AUTORIDAD,
            ruling_number=resolucion.ruling_number,
            collection=resolucion.collection,
            ruling_date=resolucion.ruling_date,
            subject=resolucion.subject,
            categories=resolucion.categories,
            tariff_codes=list(resolucion.tariff_codes),
            hs6_codes=list(resolucion.hs6_codes),
            full_text=resolucion.full_text,
            is_revoked=resolucion.is_revoked,
            revoked_by=list(resolucion.revoked_by),
            modified_by=list(resolucion.modified_by),
            related_rulings=list(resolucion.related_rulings),
            # Obra del gobierno de EE. UU.: pública, no oficial EN MÉXICO.
            data_origin="PUBLIC",
            valid_from=resolucion.ruling_date,
            published_at=resolucion.ruling_date,
            source_url=resolucion.url,
            source_document=_documento(resolucion, minio_key),
            content_hash=content_hash,
            retrieved_at=retrieved_at,
        )
    )
    return True


def _documento(resolucion: ParsedRuling, minio_key: str) -> str:
    return (
        f"CBP CROSS {resolucion.collection or ''} {resolucion.ruling_number} ({minio_key})".replace(
            "  ", " "
        )
    )
