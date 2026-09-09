"""VALIDATED -> DATABASE: artículos de la Ley Aduanera a `regulatory.legal_rules`.

`regulatory.legal_rules` estaba vacía (Persona 1, notas de
`database/repositories/notes.py`): sin ella, la RGI 1 no puede descartar una
partida por exclusión y el RAG jurídico de Persona 3 no tiene corpus. Esta
carga la puebla con los 274 artículos numerados de la Ley Aduanera.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from database.models.regulatory import LegalDocument, LegalRule, LegalSource
from database.repositories.chunks import PostgresChunkStore
from rag.types import LegalChunk, hash_contenido

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ingestion.diputados.ley_aduanera import ParsedArticle

DIPUTADOS_SLUG = "diputados"
LEY_ADUANERA_SHORT_NAME = "LEY_ADUANERA"

# "Última reforma publicada en el Diario Oficial de la Federación el 19 de
# noviembre de 2025" — verificado en LeyesBiblio/ref/ladua.htm. Es la vigencia
# del DOCUMENTO (LegalDocument.valid_from): la fecha en que la ley
# consolidada tomó su forma actual. NO es la vigencia de un artículo
# individual — usarla como respaldo por artículo fue el bug real que reportó
# Persona 3 el 2026-09-08: sin nota propia, un artículo salía "vigente desde
# 2025-11-19" aunque llevara sin tocarse desde 1995.
LEY_ADUANERA_VALID_FROM = date(2025, 11, 19)

# "Nueva Ley publicada en el Diario Oficial de la Federación el 15 de
# diciembre de 1995" — verificado en la cabecera del propio PDF (línea 11 del
# texto extraído). Respaldo de `valid_from` cuando un artículo no trae
# NINGUNA nota de reforma/adición de ningún nivel: no se ha vuelto a tocar
# desde que se promulgó la ley, así que rige desde entonces.
LEY_ADUANERA_PUBLICACION_ORIGINAL = date(1995, 12, 15)
LEY_ADUANERA_SOURCE_URL = "https://www.diputados.gob.mx/LeyesBiblio/pdf/LAdua.pdf"
LEY_ADUANERA_SOURCE_DOCUMENT = "Ley Aduanera (DOF, última reforma 19-nov-2025)"


def get_or_create_diputados_source(session: Session) -> LegalSource:
    existing = session.query(LegalSource).filter_by(slug=DIPUTADOS_SLUG).one_or_none()
    if existing is not None:
        return existing

    source = LegalSource(
        slug=DIPUTADOS_SLUG,
        name="Cámara de Diputados — Servicios Parlamentarios",
        authority="Congreso de la Unión",
        jurisdiction="MX",
        kind="OFFICIAL",
        base_url="https://www.diputados.gob.mx",
        notes=(
            "Mirror de texto consolidado, no el instrumento jurídico: las "
            "reformas se publican en el DOF. Mismo criterio que SNICE para "
            "la LIGIE (Persona 1, 2026-09-05)."
        ),
    )
    session.add(source)
    session.flush()
    return source


def get_or_create_ley_aduanera_document(
    session: Session,
    source: LegalSource,
    *,
    content_hash: str,
    retrieved_at: datetime,
) -> LegalDocument:
    existing = (
        session.query(LegalDocument).filter_by(short_name=LEY_ADUANERA_SHORT_NAME).one_or_none()
    )
    if existing is not None:
        return existing

    document = LegalDocument(
        title="Ley Aduanera",
        short_name=LEY_ADUANERA_SHORT_NAME,
        kind="LAW",
        data_origin="OFFICIAL",
        source_id=source.id,
        valid_from=LEY_ADUANERA_VALID_FROM,
        source_url=LEY_ADUANERA_SOURCE_URL,
        source_document=LEY_ADUANERA_SOURCE_DOCUMENT,
        content_hash=content_hash,
        retrieved_at=retrieved_at,
    )
    session.add(document)
    session.flush()
    return document


def to_legal_rule_row(
    parsed: ParsedArticle,
    *,
    source: LegalSource,
    document: LegalDocument,
    content_hash: str,
    retrieved_at: datetime,
) -> LegalRule:
    return LegalRule(
        legal_document_id=document.id,
        rule_number=parsed.rule_number,
        text=parsed.text,
        reform_note=parsed.reform_note,
        data_origin="OFFICIAL",
        source_id=source.id,
        valid_from=parsed.valid_from_override or LEY_ADUANERA_PUBLICACION_ORIGINAL,
        valid_to=parsed.valid_to,
        source_url=LEY_ADUANERA_SOURCE_URL,
        source_document=LEY_ADUANERA_SOURCE_DOCUMENT,
        content_hash=content_hash,
        retrieved_at=retrieved_at,
    )


def load_ley_aduanera(
    session: Session,
    *,
    articulos: list[ParsedArticle],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> int:
    """Inserta los artículos parseados. Devuelve el número de filas insertadas."""
    retrieved_at = retrieved_at or datetime.now(UTC)
    source = get_or_create_diputados_source(session)
    document = get_or_create_ley_aduanera_document(
        session, source, content_hash=content_hash, retrieved_at=retrieved_at
    )

    for parsed in articulos:
        session.add(
            to_legal_rule_row(
                parsed,
                source=source,
                document=document,
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )

    session.flush()
    return len(articulos)


def load_ley_aduanera_chunks(
    session: Session,
    *,
    articulos: list[ParsedArticle],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> int:
    """Un chunk por artículo en `regulatory.legal_chunks`, para el RAG (§27).

    Reutiliza el mismo `ParsedArticle` que llena `legal_rules` — no vuelve a
    parsear el PDF con `rag.chunking.trocear()`, que colapsa "9o.-A" a "9o.-E"
    en un único identificador "9O" y no reconoce los artículos "bis" (frente
    a esto, `ingestion.diputados.ley_aduanera` sí distingue los 274 reales;
    verificado esta sesión, no volver a intentar `trocear()` en el documento
    real sin arreglar antes esos dos huecos).

    Sin `embedding`: no hay proveedor de embeddings configurado todavía. Los
    chunks quedan recuperables por término desde hoy; `applicable()`/`search()`
    los reindexa con vector en cuanto Persona 3 lo calcule.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    source = get_or_create_diputados_source(session)
    document = get_or_create_ley_aduanera_document(
        session, source, content_hash=content_hash, retrieved_at=retrieved_at
    )

    chunks = [
        LegalChunk(
            source_id=source.id,
            document_id=document.id,
            document=document.title,
            article=parsed.rule_number,
            text=parsed.text,
            content_hash=hash_contenido(parsed.text),
            data_origin="OFFICIAL",
            valid_from=parsed.valid_from_override or LEY_ADUANERA_PUBLICACION_ORIGINAL,
            valid_to=parsed.valid_to,
            url=LEY_ADUANERA_SOURCE_URL,
        )
        for parsed in articulos
    ]
    return PostgresChunkStore(session).add(chunks)
