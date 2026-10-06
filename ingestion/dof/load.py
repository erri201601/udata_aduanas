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

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from database.models.regulatory import (
    CustomsOffice,
    LegalChunkRecord,
    LegalDocument,
    LegalRule,
    LegalSource,
    NonTariffRegulation,
    PedimentoClave,
    PedimentoIdentifier,
    UnitOfMeasure,
)
from database.repositories.chunks import PostgresChunkStore
from rag.types import LegalChunk, hash_contenido

from ingestion.dof.rgce import fracciones_de

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ingestion.dof.anexo22 import (
        ParsedCustomsOffice,
        ParsedIdentifier,
        ParsedNonTariffRegulation,
        ParsedPedimentoClave,
        ParsedUnitOfMeasure,
    )
    from ingestion.dof.rgce import ParsedRule

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
    existing = session.query(LegalDocument).filter_by(short_name=ANEXO22_SHORT_NAME).one_or_none()
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


def to_pedimento_identifier_row(
    parsed: ParsedIdentifier, *, source: LegalSource, content_hash: str, retrieved_at: datetime
) -> PedimentoIdentifier:
    return PedimentoIdentifier(
        code=parsed.code,
        level=parsed.level,
        label=parsed.label,
        supuestos_de_aplicacion=parsed.supuestos_de_aplicacion,
        **_row_kwargs(source, content_hash=content_hash, retrieved_at=retrieved_at),
    )


def load_anexo22(
    session: Session,
    *,
    offices: list[ParsedCustomsOffice],
    units: list[ParsedUnitOfMeasure],
    claves: list[ParsedPedimentoClave],
    regulations: list[ParsedNonTariffRegulation],
    identifiers: list[ParsedIdentifier],
    content_hash: str,
    retrieved_at: datetime,
) -> tuple[int, int, int, int, int]:
    """Inserta los 5 catálogos. Devuelve (aduanas, unidades, claves,
    identificadores no arancelarios, identificadores de pedimento)."""
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
    for parsed_identifier in identifiers:
        session.add(
            to_pedimento_identifier_row(
                parsed_identifier,
                source=source,
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )

    session.flush()
    return len(offices), len(units), len(claves), len(regulations), len(identifiers)


RGCE_SHORT_NAME = "RGCE_2026"
RGCE_SOURCE_URL = "https://dof.gob.mx/nota_detalle_popup.php?codigo=5777199"
RGCE_SOURCE_DOCUMENT = "RGCE 2026 (DOF)"
# Transitorio Primero, textual: "La presente Resolución entrará en vigor el
# 1o. de enero de 2026 y estará vigente hasta el 31 de diciembre de 2026."
# Es la vigencia del DOCUMENTO; la de cada regla la resuelve
# `ingestion.dof.rgce.parse_rules` cruzando los Transitorios Tercero y Cuarto.
RGCE_VALID_FROM = date(2026, 1, 1)
RGCE_VALID_TO = date(2026, 12, 31)


def get_or_create_rgce_document(
    session: Session,
    source: LegalSource,
    *,
    content_hash: str,
    retrieved_at: datetime,
) -> LegalDocument:
    existing = session.query(LegalDocument).filter_by(short_name=RGCE_SHORT_NAME).one_or_none()
    if existing is not None:
        return existing

    # `published_at` queda NULL: la nota del DOF (`nota_detalle_popup`) trae la
    # fecha de FIRMA (17-dic-2025) pero no la de publicación, y una fecha que
    # no consta en la fuente no se supone (regla 1 CLAUDE.md).
    document = LegalDocument(
        title="Reglas Generales de Comercio Exterior para 2026",
        short_name=RGCE_SHORT_NAME,
        kind="RULE",
        data_origin="OFFICIAL",
        source_id=source.id,
        valid_from=RGCE_VALID_FROM,
        valid_to=RGCE_VALID_TO,
        source_url=RGCE_SOURCE_URL,
        source_document=RGCE_SOURCE_DOCUMENT,
        content_hash=content_hash,
        retrieved_at=retrieved_at,
    )
    session.add(document)
    session.flush()
    return document


def _cargables(reglas: list[ParsedRule]) -> tuple[list[ParsedRule], list[ParsedRule]]:
    """(reglas con vigencia resuelta, reglas `needs_validation` que se excluyen).

    Las del Transitorio Cuarto entran en vigor "en términos del transitorio"
    de OTRO decreto (reforma a la Ley Aduanera, DOF 19-11-2025) que no es una
    fuente almacenada: cargarlas exigiría inventar `valid_from`. Se excluyen y
    se devuelven para reportarlas, no se descartan en silencio.
    """
    excluidas = [r for r in reglas if r.needs_validation]
    cargables = [r for r in reglas if not r.needs_validation]
    for regla in cargables:
        if regla.valid_from is None:
            raise ValueError(
                f"la regla {regla.rule_number} no trae valid_from y no está marcada "
                "needs_validation: el parser dejó pasar una vigencia sin resolver"
            )
    return cargables, excluidas


def to_rgce_legal_rule_row(
    parsed: ParsedRule,
    *,
    source: LegalSource,
    document: LegalDocument,
    content_hash: str,
    retrieved_at: datetime,
) -> LegalRule:
    assert parsed.valid_from is not None  # `_cargables` ya lo garantiza
    return LegalRule(
        legal_document_id=document.id,
        rule_number=parsed.rule_number,
        text=parsed.text,
        data_origin="OFFICIAL",
        source_id=source.id,
        valid_from=parsed.valid_from,
        valid_to=parsed.valid_to,
        source_url=RGCE_SOURCE_URL,
        source_document=RGCE_SOURCE_DOCUMENT,
        content_hash=content_hash,
        retrieved_at=retrieved_at,
    )


def load_rgce(
    session: Session,
    *,
    reglas: list[ParsedRule],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> tuple[int, list[ParsedRule]]:
    """Inserta las reglas RGCE con vigencia resuelta.

    Devuelve `(insertadas, excluidas)`: las excluidas son las `needs_validation`
    del Transitorio Cuarto, que el llamador debe reportar.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    cargables, excluidas = _cargables(reglas)
    source = get_or_create_dof_source(session)
    document = get_or_create_rgce_document(
        session, source, content_hash=content_hash, retrieved_at=retrieved_at
    )

    for parsed in cargables:
        session.add(
            to_rgce_legal_rule_row(
                parsed,
                source=source,
                document=document,
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )

    session.flush()
    return len(cargables), excluidas


def load_rgce_chunks(
    session: Session,
    *,
    reglas: list[ParsedRule],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> int:
    """Un chunk por regla cargable en `regulatory.legal_chunks`, para el RAG (§27).

    Mismo criterio que `ingestion.diputados.load.load_ley_aduanera_chunks`: sin
    `embedding` todavía, recuperable por término hasta que se vectorice. Las
    reglas `needs_validation` no llevan chunk, igual que no llevan fila.

    Además del chunk de la regla completa, una regla con fracciones romanas
    reales (`ingestion.dof.rgce.fracciones_de`) recibe un chunk POR fracción
    -- mismo criterio que `rag.chunking.trocear` con los artículos de la Ley
    Aduanera: se citan solas, así que tienen que poder recuperarse solas. Es
    lo que permite vectorizar 1.1.6/4.5.31/7.3.3 pese a que la regla completa
    no quepa en el contexto del embedder (Persona 1, 2026-09-28): cada
    fracción, mucho más corta, sí cabe.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    cargables, _ = _cargables(reglas)
    source = get_or_create_dof_source(session)
    document = get_or_create_rgce_document(
        session, source, content_hash=content_hash, retrieved_at=retrieved_at
    )

    def _chunk(article: str, texto: str, parsed: ParsedRule) -> LegalChunk:
        return LegalChunk(
            source_id=source.id,
            document_id=document.id,
            document=document.title,
            article=article,
            text=texto,
            content_hash=hash_contenido(texto),
            data_origin="OFFICIAL",
            valid_from=parsed.valid_from,
            valid_to=parsed.valid_to,
            url=RGCE_SOURCE_URL,
        )

    chunks: list[LegalChunk] = []
    for parsed in cargables:
        chunks.append(_chunk(parsed.rule_number, parsed.text, parsed))
        for romano, fragmento in fracciones_de(parsed.text):
            chunks.append(_chunk(f"{parsed.rule_number} fracción {romano}", fragmento, parsed))

    return PostgresChunkStore(session).add(chunks)


def add_fraccion_chunks_for_long_rules(
    session: Session,
    *,
    reglas: list[ParsedRule],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> int:
    """Agrega los chunks por fracción que le faltan a una carga YA HECHA.

    Existe por la misma razón que `add_missing_coves`: 1.1.6, 4.5.31 y 7.3.3
    ya tenían su chunk de regla completa (sin `embedding`, saltado por el
    backfill) antes de que `fracciones_de` existiera -- esto no vuelve a
    insertar ESE chunk (ya está, y re-enviarlo reventaría la unicidad), sólo
    agrega los de fracción que faltan. Idempotente: una fracción ya
    insertada no se repite.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    cargables, _ = _cargables(reglas)
    source = get_or_create_dof_source(session)
    document = get_or_create_rgce_document(
        session, source, content_hash=content_hash, retrieved_at=retrieved_at
    )

    ya_existen = {
        (article, valid_from)
        for article, valid_from in session.query(
            LegalChunkRecord.article, LegalChunkRecord.valid_from
        ).filter(LegalChunkRecord.legal_document_id == document.id)
    }

    chunks: list[LegalChunk] = []
    for parsed in cargables:
        for romano, fragmento in fracciones_de(parsed.text):
            article = f"{parsed.rule_number} fracción {romano}"
            if (article, parsed.valid_from) in ya_existen:
                continue
            chunks.append(
                LegalChunk(
                    source_id=source.id,
                    document_id=document.id,
                    document=document.title,
                    article=article,
                    text=fragmento,
                    content_hash=hash_contenido(fragmento),
                    data_origin="OFFICIAL",
                    valid_from=parsed.valid_from,
                    valid_to=parsed.valid_to,
                    url=RGCE_SOURCE_URL,
                )
            )

    if not chunks:
        return 0
    return PostgresChunkStore(session).add(chunks)


def add_missing_identifier_text(
    session: Session,
    *,
    identifiers: list[ParsedIdentifier],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> tuple[int, int]:
    """Backfill DIRIGIDO del Apéndice 8 (decisión de Persona 1, 6-oct): enriquece
    con `label`/`supuestos_de_aplicacion` las 174 filas ya cargadas (PR #158,
    sólo `code`+`level`) y agrega las que falten -- CR, EO, PB y PO, perdidas
    en la carga original por un regex que sólo aceptaba guión normal ("-") y
    no guión largo ("–"), encontrado al extraer este mismo texto (ver
    `ingestion.dof.anexo22._IDENTIFICADOR_APENDICE_RE`).

    Identidad por `(code, level)`, igual que la `UniqueConstraint` de la
    tabla. Idempotente: una fila que ya tiene `label` no se vuelve a tocar
    (no hay vigencia de la que cerrar una versión anterior -- es el mismo
    documento, sólo se le agrega lo que antes no se cargó). Devuelve
    (filas nuevas, filas enriquecidas).
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    source = get_or_create_dof_source(session)

    existentes = {(f.code, f.level): f for f in session.query(PedimentoIdentifier).all()}

    creadas = 0
    enriquecidas = 0
    for parsed in identifiers:
        clave = (parsed.code, parsed.level)
        fila = existentes.get(clave)
        if fila is None:
            session.add(
                to_pedimento_identifier_row(
                    parsed, source=source, content_hash=content_hash, retrieved_at=retrieved_at
                )
            )
            creadas += 1
            continue
        if fila.label is None and parsed.label is not None:
            fila.label = parsed.label
            fila.supuestos_de_aplicacion = parsed.supuestos_de_aplicacion
            enriquecidas += 1

    session.flush()
    return creadas, enriquecidas


def load_identifier_chunks(
    session: Session,
    *,
    identifiers: list[ParsedIdentifier],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> int:
    """Un chunk de RAG por identificador del Apéndice 8 que ya tenga
    `label`+`supuestos_de_aplicacion` -- lector real: el RAG/AduLex
    (decisión de Persona 1, 6-oct), NO `required_identifiers` todavía (ver
    `docs/RECONOCIMIENTO_APENDICE_8.md`). Idempotente, mismo patrón que
    `add_fraccion_chunks_for_long_rules`.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    source = get_or_create_dof_source(session)
    document = get_or_create_anexo22_document(
        session, source, content_hash=content_hash, retrieved_at=retrieved_at
    )

    ya_existen = {
        (article, valid_from)
        for article, valid_from in session.query(
            LegalChunkRecord.article, LegalChunkRecord.valid_from
        ).filter(LegalChunkRecord.legal_document_id == document.id)
    }

    chunks: list[LegalChunk] = []
    for parsed in identifiers:
        if not parsed.label or not parsed.supuestos_de_aplicacion:
            continue
        nivel = f" (nivel {parsed.level})" if parsed.level else ""
        # El nivel va en el article, no sólo en el texto: 6 claves reales
        # repiten código con G Y P, cada una con su propio supuesto (p. ej.
        # "CF" -- ver `_identificadores_de_pagina`) -- sin el nivel aquí,
        # la segunda chocaba contra `ya_existen` de la primera y su propio
        # supuesto nunca entraba al RAG, aunque la fila sí quedara completa
        # en `pedimento_identifiers`.
        article = f"Apéndice 8, clave {parsed.code}{nivel}"
        if (article, ANEXO22_VALID_FROM) in ya_existen:
            continue
        texto = (
            f"Identificador de pedimento {parsed.code}{nivel}: {parsed.label} "
            f"Supuestos de aplicación: {parsed.supuestos_de_aplicacion}"
        )
        chunks.append(
            LegalChunk(
                source_id=source.id,
                document_id=document.id,
                document=document.title,
                article=article,
                text=texto,
                content_hash=hash_contenido(texto),
                data_origin="OFFICIAL",
                valid_from=ANEXO22_VALID_FROM,
                url=ANEXO22_SOURCE_URL,
            )
        )

    if not chunks:
        return 0
    return PostgresChunkStore(session).add(chunks)
