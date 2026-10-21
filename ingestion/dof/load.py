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

import re
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from database.models.regulatory import (
    CustomsOffice,
    LegalChunkRecord,
    LegalDocument,
    LegalRule,
    LegalSource,
    NonTariffRegulation,
    PedimentoClave,
    PedimentoIdentifier,
    PedimentoIdentifierRequirement,
    RegulatoryEvent,
    UnitOfMeasure,
)
from database.repositories.chunks import PostgresChunkStore
from rag.types import LegalChunk, hash_contenido

from ingestion.dof.rgce import fracciones_de
from ingestion.dof.sumario import clasificar_event_kind

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import Session

    from ingestion.dof.anexo22 import (
        ParsedCustomsOffice,
        ParsedIdentifier,
        ParsedNonTariffRegulation,
        ParsedPedimentoClave,
        ParsedUnitOfMeasure,
    )
    from ingestion.dof.apendice_8_requisitos import ParsedIdentifierRequirement
    from ingestion.dof.rgce import ParsedRule
    from ingestion.dof.sumario import ParsedSumarioItem

log = structlog.stdlib.get_logger("ingestion.dof.load")

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


def load_regulatory_events(
    session: Session,
    *,
    items: list[ParsedSumarioItem],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> int:
    """Carga `regulatory_events` (§11 DOF, §43 Sprint 6) -- lo mínimo que
    hace que el Sentinel deje de decir "sin vigilancia": `eventos_dof` deja
    de ser 0 en cuanto esto corre una vez.

    `items` ya viene filtrado a relevancia de comercio exterior
    (`ingestion.dof.sumario.es_relevante_comercio_exterior`) -- este loader
    no decide relevancia, sólo escribe.

    `affected_fraction_codes`/`affected_rule_ids` quedan `[]` (el default
    de la columna): identificar qué fracción o regla afecta un decreto
    exige leer el documento completo, no el resumen de una línea del
    sumario -- afirmarlo desde ahí sería inventar (§8.1 maestro). El
    Sentinel hoy sólo cuenta filas (`apps/api/routers/sentinel.py`); que
    muestre "qué cambió" con `title`/`summary` es cableado de quien lo
    decida, igual que `required_identifiers` (ADR 0010).

    Identidad por `source_url` (único por `codigo` del DOF) -- idempotente,
    mismo criterio que `cargar_cuotas_compensatorias`.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    source = get_or_create_dof_source(session)

    existentes = {url for (url,) in session.query(RegulatoryEvent.source_url).all()}

    creados = 0
    for item in items:
        if item.source_url in existentes:
            continue
        existentes.add(item.source_url)
        session.add(
            RegulatoryEvent(
                title=item.description,
                authority=item.authority,
                event_kind=clasificar_event_kind(item),
                effective_date=None,
                summary=item.description,
                keywords=[],
                affected_fraction_codes=[],
                affected_rule_ids=[],
                data_origin="OFFICIAL",
                source_id=source.id,
                valid_from=item.value_date,
                published_at=item.value_date,
                source_url=item.source_url,
                source_document=f"DOF, sumario diario ({item.value_date.isoformat()})",
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )
        creados += 1

    session.flush()
    log.info("dof.regulatory_events.cargado", creados=creados, recibidos=len(items))
    return creados


def load_identifier_requirements(
    session: Session,
    *,
    requisitos: Sequence[ParsedIdentifierRequirement],
    content_hash: str,
    retrieved_at: datetime | None = None,
) -> int:
    """Carga `regulatory.pedimento_identifier_requirements` (ADR 0012).

    Cada regla es «la clave de pedimento X exige el identificador Y en el
    nivel G». Sólo entran las que ya pasaron
    `apendice_8_requisitos.verificar_contra_el_documento`.

    Idempotente por `(identifier_code, condition_kind, condition_value,
    valid_from)`, la `UniqueConstraint` de la tabla. No reconcilia una fila ya
    cargada.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    source = get_or_create_dof_source(session)
    existentes = set(
        session.execute(
            sa.select(
                PedimentoIdentifierRequirement.identifier_code,
                PedimentoIdentifierRequirement.condition_kind,
                PedimentoIdentifierRequirement.condition_value,
                PedimentoIdentifierRequirement.valid_from,
            )
        ).tuples()
    )
    creadas = 0
    for req in requisitos:
        clave = (req.identifier_code, "PEDIMENTO_KEY", req.pedimento_key, ANEXO22_VALID_FROM)
        if clave in existentes:
            continue
        existentes.add(clave)
        session.add(
            PedimentoIdentifierRequirement(
                identifier_code=req.identifier_code,
                identifier_level=req.identifier_level,
                condition_kind="PEDIMENTO_KEY",
                condition_value=req.pedimento_key,
                scope_note=req.supuesto,
                **_row_kwargs(source, content_hash=content_hash, retrieved_at=retrieved_at),
            )
        )
        creadas += 1
    session.flush()
    return creadas


def leer_notas_pendientes(
    session: Session,
    *,
    descargar: Callable[[str], bytes],
    guardar_raw: Callable[[bytes, str], str],
    todas: bool = False,
) -> tuple[int, int]:
    """Lee la nota de cada evento que aún no se leyó (ADR 0022).

    `descargar(url)` trae la nota; `guardar_raw(bytes, codigo)` la sube a RAW y
    devuelve su hash. Llena `affected_fraction_codes`, añade a `keywords` las
    NOM del título, y fija `effective_date` (y `valid_to`, si el decreto dice
    cuánto dura) sólo cuando el transitorio es inequívoco.

    Con `todas`, vuelve a leer también las ya leídas: sirve cuando el lector
    mejora (21-oct: un «Transitorio Tercero» citado en los considerandos le
    quitaba la fecha al Código de Conducta de la SE).

    Devuelve `(leídas, con_fracciones)`. Una nota que no se pudo descargar se
    deja pendiente para la siguiente pasada.
    """
    from ingestion.dof.afectacion import leer

    consulta = sa.select(RegulatoryEvent)
    if not todas:
        consulta = consulta.where(RegulatoryEvent.note_content_hash.is_(None))
    pendientes = session.scalars(consulta).all()
    leidas = con_fracciones = 0
    for evento in pendientes:
        url = re.sub(r"^https?://(www\.)?dof\.gob\.mx", "https://dof.gob.mx", evento.source_url)
        codigo = re.search(r"codigo=(\d+)", url)
        try:
            datos = descargar(url)
        except Exception as exc:
            log.warning("dof.nota.no_descargada", url=url, error=type(exc).__name__)
            continue
        publicada = evento.published_at or evento.valid_from
        afectacion = leer(
            datos.decode("utf-8", errors="replace"), titulo=evento.title, publicada=publicada
        )
        evento.affected_fraction_codes = list(afectacion.fracciones)
        evento.keywords = list(dict.fromkeys([*evento.keywords, *afectacion.noms]))
        if afectacion.entra_en_vigor is not None and (todas or evento.effective_date is None):
            evento.effective_date = afectacion.entra_en_vigor
        if afectacion.vigencia_hasta is not None:
            evento.valid_to = afectacion.vigencia_hasta
        evento.note_content_hash = guardar_raw(datos, codigo.group(1) if codigo else "sin_codigo")
        leidas += 1
        con_fracciones += int(bool(afectacion.fracciones))
    session.flush()
    log.info(
        "dof.notas.leidas", leidas=leidas, con_fracciones=con_fracciones, pendientes=len(pendientes)
    )
    return leidas, con_fracciones
