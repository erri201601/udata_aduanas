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
    load_rgce,
    load_rgce_chunks,
)
from ingestion.dof.rgce import TRANSITORIO_CUARTO_MOTIVO, ParsedRule
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

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
NUMEROS_DE_PRUEBA = {NORMAL, FEBRERO_REGLA, EXCLUIDA}

INICIO = date(2026, 1, 1)
FIN = date(2026, 12, 31)
FEBRERO = date(2026, 2, 2)


def _regla(numero: str, *, desde: date | None = INICIO, **extra: object) -> ParsedRule:
    return ParsedRule(
        rule_number=numero,
        text=f"Texto de la regla {numero}.",
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
