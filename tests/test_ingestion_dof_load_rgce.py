"""Tests del loader de las RGCE 2026 (`ingestion.dof.load.load_rgce`).

Las pruebas unitarias cubren la regla de exclusión; las de integración
(`pg_session`, savepoint + rollback) cubren lo que sólo se ve contra
Postgres: vigencia por regla, documento, y que lo excluido NO llega a la base.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.regulatory import LegalChunkRecord, LegalDocument, LegalRule
from ingestion.dof.load import (
    RGCE_SHORT_NAME,
    _cargables,
    add_fraccion_chunks_for_long_rules,
    load_rgce,
    load_rgce_chunks,
)
from ingestion.dof.rgce import TRANSITORIO_CUARTO_MOTIVO, ParsedRule
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from tests.fixtures.rgce_2026_regla_larga_fragmento import REGLA_1_1_6_FRAGMENTO

if TYPE_CHECKING:
    from collections.abc import Iterator

HASH = "a" * 64

# Números de regla que NO existen en el documento real (los Títulos reales de
# las RGCE 2026 llegan a 7): la base local puede tener ya las 537 reales
# cargadas, y `(documento, regla, valid_from)` es único -- con reglas de prueba
# "1.1.1" el test chocaría contra la carga real (regresión real, 2026-09-28).
NORMAL = "9.9.1"
FEBRERO_REGLA = "9.9.2"
EXCLUIDA = "9.9.3"
CON_FRACCIONES = "9.9.4"
NUMEROS_DE_PRUEBA = {NORMAL, FEBRERO_REGLA, EXCLUIDA, CON_FRACCIONES}

INICIO = date(2026, 1, 1)
FIN = date(2026, 12, 31)
FEBRERO = date(2026, 2, 2)


def _regla(
    numero: str, *, desde: date | None = INICIO, texto: str | None = None, **extra: object
) -> ParsedRule:
    return ParsedRule(
        rule_number=numero,
        text=texto or f"Texto de la regla {numero}.",
        valid_from=desde,
        valid_to=FIN if desde else None,
        **extra,  # type: ignore[arg-type]
    )


def _reglas() -> list[ParsedRule]:
    return [
        _regla(NORMAL),
        _regla(FEBRERO_REGLA, desde=FEBRERO),
        _regla(
            EXCLUIDA,
            desde=None,
            needs_validation=True,
            needs_validation_reason=TRANSITORIO_CUARTO_MOTIVO,
        ),
    ]


@pytest.fixture
def pg_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Sesión contra el Postgres local. Salta el test si no hay conexión."""
    from apps.api.config import get_settings

    monkeypatch.setenv("ADUANERO_ENV_FILE", ".env")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    engine = sa.create_engine(get_settings().sqlalchemy_url)
    try:
        conn = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"sin PostgreSQL local: {exc}")
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()
        engine.dispose()


@pytest.mark.unit
def test_las_needs_validation_se_excluyen_y_se_devuelven() -> None:
    cargables, excluidas = _cargables(_reglas())

    assert [r.rule_number for r in cargables] == [NORMAL, FEBRERO_REGLA]
    assert [r.rule_number for r in excluidas] == [EXCLUIDA]


@pytest.mark.unit
def test_una_regla_sin_valid_from_y_sin_marca_no_pasa_en_silencio() -> None:
    """Si el parser dejara pasar una vigencia sin resolver, cargarla exigiría
    inventar `valid_from` -- el loader falla ruidoso en vez de adivinar."""
    with pytest.raises(ValueError, match=r"9\.9\.1"):
        _cargables([_regla(NORMAL, desde=None)])


@pytest.mark.integration
def test_load_rgce_inserta_con_la_vigencia_de_cada_regla(pg_session: Session) -> None:
    insertadas, excluidas = load_rgce(pg_session, reglas=_reglas(), content_hash=HASH)

    assert insertadas == 2
    assert [r.rule_number for r in excluidas] == [EXCLUIDA]

    filas = {
        f.rule_number: f
        for f in pg_session.query(LegalRule)
        .join(LegalDocument, LegalDocument.id == LegalRule.legal_document_id)
        .filter(
            LegalDocument.short_name == RGCE_SHORT_NAME,
            LegalRule.rule_number.in_(NUMEROS_DE_PRUEBA),
        )
    }
    assert set(filas) == {NORMAL, FEBRERO_REGLA}
    assert (filas[NORMAL].valid_from, filas[NORMAL].valid_to) == (INICIO, FIN)
    assert (filas[FEBRERO_REGLA].valid_from, filas[FEBRERO_REGLA].valid_to) == (FEBRERO, FIN)
    assert all(f.data_origin == "OFFICIAL" and f.content_hash == HASH for f in filas.values())


@pytest.mark.integration
def test_lo_excluido_no_llega_a_la_base(pg_session: Session) -> None:
    load_rgce(pg_session, reglas=_reglas(), content_hash=HASH)

    hay = (
        pg_session.query(LegalRule)
        .join(LegalDocument, LegalDocument.id == LegalRule.legal_document_id)
        .filter(LegalDocument.short_name == RGCE_SHORT_NAME, LegalRule.rule_number == EXCLUIDA)
        .count()
    )
    assert hay == 0


@pytest.mark.integration
def test_el_documento_lleva_la_vigencia_del_transitorio_primero_y_no_inventa_publicacion(
    pg_session: Session,
) -> None:
    load_rgce(pg_session, reglas=_reglas(), content_hash=HASH)

    doc = pg_session.query(LegalDocument).filter_by(short_name=RGCE_SHORT_NAME).one()
    assert (doc.valid_from, doc.valid_to) == (INICIO, FIN)
    assert doc.kind == "RULE"
    assert doc.published_at is None


@pytest.mark.integration
def test_los_chunks_siguen_la_misma_regla_de_exclusion_y_ligan_su_regla(
    pg_session: Session,
) -> None:
    """Cargadas las reglas primero, cada chunk resuelve su `legal_rule_id` por
    la terna (documento, artículo, valid_from); el excluido no tiene chunk."""
    load_rgce(pg_session, reglas=_reglas(), content_hash=HASH)
    n = load_rgce_chunks(pg_session, reglas=_reglas(), content_hash=HASH)

    assert n == 2
    chunks = {
        c.article: c
        for c in pg_session.query(LegalChunkRecord)
        .join(LegalDocument, LegalDocument.id == LegalChunkRecord.legal_document_id)
        .filter(
            LegalDocument.short_name == RGCE_SHORT_NAME,
            LegalChunkRecord.article.in_(NUMEROS_DE_PRUEBA),
        )
    }
    assert set(chunks) == {NORMAL, FEBRERO_REGLA}
    assert all(c.legal_rule_id is not None for c in chunks.values())
    assert chunks[FEBRERO_REGLA].valid_from == FEBRERO


@pytest.mark.integration
def test_una_regla_con_fracciones_reales_recibe_un_chunk_por_fraccion(
    pg_session: Session,
) -> None:
    """REGRESIÓN REAL (Persona 1, 2026-09-28): 1.1.6, 4.5.31 y 7.3.3 (hasta
    46 094 caracteres) no caben en el embedder -- partidas por fracción, cada
    fragmento sí cabe. Con el fragmento real de 1.1.6 (tres fracciones): un
    chunk de la regla completa + uno por cada fracción."""
    regla = _regla(CON_FRACCIONES, texto=REGLA_1_1_6_FRAGMENTO)
    load_rgce(pg_session, reglas=[regla], content_hash=HASH)
    n = load_rgce_chunks(pg_session, reglas=[regla], content_hash=HASH)

    assert n == 4  # la regla completa + fracciones I, II, III
    chunks = {
        c.article: c
        for c in pg_session.query(LegalChunkRecord)
        .join(LegalDocument, LegalDocument.id == LegalChunkRecord.legal_document_id)
        .filter(
            LegalDocument.short_name == RGCE_SHORT_NAME,
            LegalChunkRecord.article.like(f"{CON_FRACCIONES}%"),
        )
    }
    assert set(chunks) == {
        CON_FRACCIONES,
        f"{CON_FRACCIONES} fracción I",
        f"{CON_FRACCIONES} fracción II",
        f"{CON_FRACCIONES} fracción III",
    }
    # La regla completa sí liga con legal_rules (mismo rule_number exacto);
    # los chunks de fracción no -- mismo criterio ya aceptado para la Ley
    # Aduanera (`rag.chunking.trocear`): el article de una fracción nunca
    # coincide con ningún rule_number, así que quedan sin ligar a propósito.
    assert chunks[CON_FRACCIONES].legal_rule_id is not None
    assert chunks[f"{CON_FRACCIONES} fracción I"].legal_rule_id is None
    assert len(chunks[f"{CON_FRACCIONES} fracción II"].text) < len(REGLA_1_1_6_FRAGMENTO)


@pytest.mark.integration
def test_add_fraccion_chunks_rellena_una_carga_anterior_sin_partir(
    pg_session: Session,
) -> None:
    """El estado real antes de esta tarea: la regla y su chunk COMPLETO ya
    estaban cargados (el backfill lo saltó por no caber en el embedder) --
    `add_fraccion_chunks_for_long_rules` agrega sólo lo que falta, sin volver
    a insertar el chunk completo (reventaría la unicidad)."""
    regla = _regla(CON_FRACCIONES, texto=REGLA_1_1_6_FRAGMENTO)
    load_rgce(pg_session, reglas=[regla], content_hash=HASH)
    load_rgce_chunks(pg_session, reglas=[regla], content_hash=HASH)
    # Simula el estado previo: sólo el chunk de la regla completa, sin las
    # fracciones (como si `load_rgce_chunks` aún no supiera partir).
    pg_session.query(LegalChunkRecord).filter(
        LegalChunkRecord.article.like(f"{CON_FRACCIONES} fracción%")
    ).delete(synchronize_session=False)
    pg_session.flush()

    creados = add_fraccion_chunks_for_long_rules(pg_session, reglas=[regla], content_hash=HASH)

    assert creados == 3
    articulos = {
        c.article
        for c in pg_session.query(LegalChunkRecord).filter(
            LegalChunkRecord.article.like(f"{CON_FRACCIONES}%")
        )
    }
    assert articulos == {
        CON_FRACCIONES,
        f"{CON_FRACCIONES} fracción I",
        f"{CON_FRACCIONES} fracción II",
        f"{CON_FRACCIONES} fracción III",
    }


@pytest.mark.integration
def test_add_fraccion_chunks_es_idempotente(pg_session: Session) -> None:
    regla = _regla(CON_FRACCIONES, texto=REGLA_1_1_6_FRAGMENTO)
    load_rgce(pg_session, reglas=[regla], content_hash=HASH)
    load_rgce_chunks(pg_session, reglas=[regla], content_hash=HASH)

    creados = add_fraccion_chunks_for_long_rules(pg_session, reglas=[regla], content_hash=HASH)

    assert creados == 0
