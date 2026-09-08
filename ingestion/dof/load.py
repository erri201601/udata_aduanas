"""VALIDATED -> DATABASE: catálogos del Anexo 22 al Canonical Model.

Los 4 catálogos (aduanas/secciones, unidades de medida, claves de pedimento,
identificadores no arancelarios) vienen de un solo documento — un `LegalSource`
(DOF) y un `LegalDocument` (Anexo 22) bastan para los cuatro.

A diferencia de `tariff_fractions`/`nicos`, estas tablas no llevan
`UniqueConstraint` compuesta con `valid_from`: cada código tiene una sola fila
vigente por diseño (catálogos de referencia que casi no cambian). Una
recarga con los mismos códigos falla ruidoso contra la unicidad en vez de
duplicar en silencio — si el Anexo 22 se republica con cambios reales, cerrar
la versión anterior a mano es la corrección correcta, no una reconciliación
automática que hoy nadie pidió.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from database.models.regulatory import (
    CustomsOffice,
    LegalDocument,
    LegalSource,
    NonTariffRegulation,
    PedimentoClave,
    UnitOfMeasure,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from ingestion.dof.anexo22 import (
        ParsedCustomsOffice,
        ParsedNonTariffRegulation,
        ParsedPedimentoClave,
        ParsedUnitOfMeasure,
    )

DOF_SLUG = "dof"
ANEXO22_SHORT_NAME = "ANEXO_22_RGCE_2026"

# Publicado en el DOF el 15-ene-2026 (RGCE 2026) — verificado contra el propio
# encabezado del documento ("Jueves 15 de enero de 2026") en cada página.
ANEXO22_VALID_FROM = date(2026, 1, 15)
ANEXO22_SOURCE_URL = "https://dof.gob.mx/abrirPDF.php?anio=2026&archivo=15012026-MAT.pdf"
ANEXO22_SOURCE_DOCUMENT = "Anexo 22 RGCE 2026 (DOF)"


def get_or_create_dof_source(session: Session) -> LegalSource:
    existing = session.query(LegalSource).filter_by(slug=DOF_SLUG).one_or_none()
    if existing is not None:
        return existing

    source = LegalSource(
        slug=DOF_SLUG,
        name="Diario Oficial de la Federación",
        authority="Secretaría de Gobernación",
        jurisdiction="MX",
        kind="OFFICIAL",
        base_url="https://www.dof.gob.mx",
    )
    session.add(source)
    session.flush()
    return source


def get_or_create_anexo22_document(
    session: Session,
    source: LegalSource,
    *,
    content_hash: str,
    retrieved_at: datetime,
) -> LegalDocument:
    existing = (
        session.query(LegalDocument).filter_by(short_name=ANEXO22_SHORT_NAME).one_or_none()
    )
    if existing is not None:
        return existing

    document = LegalDocument(
        title="Anexo 22 de las Reglas Generales de Comercio Exterior — Instructivo para el llenado del pedimento",
        short_name=ANEXO22_SHORT_NAME,
        kind="ANNEX",
        data_origin="OFFICIAL",
        source_id=source.id,
        valid_from=ANEXO22_VALID_FROM,
        source_url=ANEXO22_SOURCE_URL,
        source_document=ANEXO22_SOURCE_DOCUMENT,
        content_hash=content_hash,
        retrieved_at=retrieved_at,
    )
    session.add(document)
    session.flush()
    return document


def _row_kwargs(source: LegalSource, *, content_hash: str, retrieved_at: datetime) -> dict:
    return {
        "data_origin": "OFFICIAL",
        "source_id": source.id,
        "valid_from": ANEXO22_VALID_FROM,
        "source_url": ANEXO22_SOURCE_URL,
        "source_document": ANEXO22_SOURCE_DOCUMENT,
        "content_hash": content_hash,
        "retrieved_at": retrieved_at,
    }


def to_customs_office_row(
    parsed: ParsedCustomsOffice, *, source: LegalSource, content_hash: str, retrieved_at: datetime
) -> CustomsOffice:
    return CustomsOffice(
        aduana=parsed.aduana,
        seccion=parsed.seccion,
        name=parsed.name,
        **_row_kwargs(source, content_hash=content_hash, retrieved_at=retrieved_at),
    )


def to_unit_of_measure_row(
    parsed: ParsedUnitOfMeasure, *, source: LegalSource, content_hash: str, retrieved_at: datetime
) -> UnitOfMeasure:
    return UnitOfMeasure(
        code=parsed.code,
        description=parsed.description,
        **_row_kwargs(source, content_hash=content_hash, retrieved_at=retrieved_at),
    )


def to_pedimento_clave_row(
    parsed: ParsedPedimentoClave, *, source: LegalSource, content_hash: str, retrieved_at: datetime
) -> PedimentoClave:
    return PedimentoClave(
        code=parsed.code,
        label=None,
        supuestos_de_aplicacion=None,
        **_row_kwargs(source, content_hash=content_hash, retrieved_at=retrieved_at),
    )


def to_non_tariff_regulation_row(
    parsed: ParsedNonTariffRegulation,
    *,
    source: LegalSource,
    content_hash: str,
    retrieved_at: datetime,
) -> NonTariffRegulation:
    return NonTariffRegulation(
        code=parsed.code,
        issuing_agency=parsed.issuing_agency,
        description=parsed.description,
        **_row_kwargs(source, content_hash=content_hash, retrieved_at=retrieved_at),
    )


def load_anexo22(
    session: Session,
    *,
    offices: list[ParsedCustomsOffice],
    units: list[ParsedUnitOfMeasure],
    claves: list[ParsedPedimentoClave],
    regulations: list[ParsedNonTariffRegulation],
    content_hash: str,
    retrieved_at: datetime,
) -> tuple[int, int, int, int]:
    """Inserta los 4 catálogos. Devuelve (aduanas, unidades, claves, identificadores)."""
    source = get_or_create_dof_source(session)
    get_or_create_anexo22_document(
        session, source, content_hash=content_hash, retrieved_at=retrieved_at
    )

    for parsed_office in offices:
        session.add(
            to_customs_office_row(
                parsed_office, source=source, content_hash=content_hash, retrieved_at=retrieved_at
            )
        )
    for parsed_unit in units:
        session.add(
            to_unit_of_measure_row(
                parsed_unit, source=source, content_hash=content_hash, retrieved_at=retrieved_at
            )
        )
    for parsed_clave in claves:
        session.add(
            to_pedimento_clave_row(
                parsed_clave, source=source, content_hash=content_hash, retrieved_at=retrieved_at
            )
        )
    for parsed_regulation in regulations:
        session.add(
            to_non_tariff_regulation_row(
                parsed_regulation,
                source=source,
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )

    session.flush()
    return len(offices), len(units), len(claves), len(regulations)
