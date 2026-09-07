"""VALIDATED -> DATABASE: filas parseadas de SNICE al Canonical Model.

Antes de escribir una sola fila, registra el ancla de trazabilidad
(`LegalSource` de SNICE) y el instrumento jurídico (`LegalDocument` de la
LIGIE 2022) — sin ellos no hay `source_id` a quién apuntar.

Regla del proyecto: nunca correr esto primero contra la base compartida.
Siempre una corrida en seco contra Postgres local antes.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from database.models.regulatory import LegalDocument, LegalSource, Nico, TariffFraction

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ingestion.snice.nico import ParsedNico
    from ingestion.snice.tariff import ParsedFraction

SNICE_SLUG = "snice"
LIGIE_SHORT_NAME = "LIGIE"

# El original de la LIGIE 2022 (`LIGIE_2022_orig_07jun22`, diputados.gob.mx) —
# fecha real, no supuesta: es el nombre del archivo que publica la Cámara.
LIGIE_VALID_FROM = date(2022, 6, 7)
LIGIE_SOURCE_URL = "https://www.diputados.gob.mx/LeyesBiblio/ref/ligie_2022.htm"


def get_or_create_snice_source(session: Session) -> LegalSource:
    """El `LegalSource` real de SNICE (no el `demo-snice` sintético de los seeds)."""
    existing = session.query(LegalSource).filter_by(slug=SNICE_SLUG).one_or_none()
    if existing is not None:
        return existing

    source = LegalSource(
        slug=SNICE_SLUG,
        name="Sistema Nacional de Información de Comercio Exterior (SNICE)",
        authority="Secretaría de Economía",
        jurisdiction="MX",
        kind="OFFICIAL",
        base_url="https://www.snice.gob.mx",
        notes=(
            "Para NICO, SNICE es la fuente. Para la tarifa (LIGIE), SNICE es "
            "complementaria: el instrumento jurídico es la LIGIE publicada en "
            "el DOF; si el portal y la ley divergen, gana la ley. "
            "Decisión de Persona 1, 2026-09-05 — no dejarlo implícito."
        ),
    )
    session.add(source)
    session.flush()
    return source


def get_or_create_ligie_document(
    session: Session,
    source: LegalSource,
    *,
    content_hash: str,
    retrieved_at: datetime,
) -> LegalDocument:
    """El `LegalDocument` de la LIGIE 2022 — el instrumento jurídico, no el render."""
    existing = session.query(LegalDocument).filter_by(short_name=LIGIE_SHORT_NAME).one_or_none()
    if existing is not None:
        return existing

    document = LegalDocument(
        title="Ley de los Impuestos Generales de Importación y de Exportación (Tarifa)",
        short_name=LIGIE_SHORT_NAME,
        kind="TARIFF",
        data_origin="OFFICIAL",
        source_id=source.id,
        valid_from=LIGIE_VALID_FROM,
        source_url=LIGIE_SOURCE_URL,
        source_document="LIGIE 2022 (DOF)",
        content_hash=content_hash,
        retrieved_at=retrieved_at,
    )
    session.add(document)
    session.flush()
    return document


def to_tariff_fraction_row(
    parsed: ParsedFraction,
    *,
    source: LegalSource,
    document: LegalDocument,
) -> TariffFraction:
    return TariffFraction(
        code=parsed.code,
        chapter=parsed.chapter,
        heading=parsed.heading,
        subheading=parsed.subheading,
        description=parsed.description,
        unit=parsed.unit,
        igi_rate=parsed.igi_rate,
        ige_rate=parsed.ige_rate,
        specificity=parsed.specificity,
        legal_document_id=document.id,
        data_origin="OFFICIAL",
        source_id=source.id,
        valid_from=LIGIE_VALID_FROM,
        source_url=parsed.source_url,
        source_document=parsed.source_document,
        content_hash=parsed.content_hash,
        retrieved_at=parsed.retrieved_at,
    )


def to_nico_row(parsed: ParsedNico, *, source: LegalSource, tariff_fraction_id: object) -> Nico:
    return Nico(
        tariff_fraction_id=tariff_fraction_id,
        code=parsed.code,
        full_code=parsed.full_code,
        description=parsed.description,
        data_origin="OFFICIAL",
        source_id=source.id,
        valid_from=LIGIE_VALID_FROM,
        source_url=parsed.source_url,
        source_document=parsed.source_document,
        content_hash=parsed.content_hash,
        retrieved_at=parsed.retrieved_at,
    )


def load_chapters(
    session: Session,
    *,
    fracciones: list[ParsedFraction],
    nicos: list[ParsedNico],
    ligie_content_hash: str,
) -> tuple[int, int]:
    """Inserta fracciones y NICO ya parseados. Devuelve (n_fracciones, n_nicos).

    `Nico.tariff_fraction_id` se resuelve aquí, por eso las fracciones se
    insertan primero: no existe sin la fracción a la que pertenece.
    """
    source = get_or_create_snice_source(session)
    document = get_or_create_ligie_document(
        session,
        source,
        content_hash=ligie_content_hash,
        retrieved_at=datetime.now(UTC),
    )

    fraction_id_by_code: dict[str, object] = {}
    for parsed_fraction in fracciones:
        row = to_tariff_fraction_row(parsed_fraction, source=source, document=document)
        session.add(row)
        session.flush()
        fraction_id_by_code[parsed_fraction.code] = row.id

    nico_rows = 0
    for parsed_nico in nicos:
        fraction_id = fraction_id_by_code.get(parsed_nico.fraction_code)
        if fraction_id is None:
            # La fracción no se insertó (p. ej. fue rechazada, como "Prohibida").
            # Un NICO sin fracción viola la FK — se omite, no se inventa un id.
            continue
        session.add(to_nico_row(parsed_nico, source=source, tariff_fraction_id=fraction_id))
        nico_rows += 1

    session.flush()
    return len(fraction_id_by_code), nico_rows
