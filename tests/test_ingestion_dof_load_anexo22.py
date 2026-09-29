"""Tests de integración de `ingestion.dof.load.load_anexo22`, centrados en
`PedimentoIdentifier` (Apéndice 8) -- lo que agrega esta tarea. Los otros
4 catálogos ya se prueban indirectamente por el parser; aquí van vacíos."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.regulatory import PedimentoIdentifier
from ingestion.dof.anexo22 import ParsedIdentifier
from ingestion.dof.load import load_anexo22
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

HASH = "b" * 64

# Códigos que no existen en el documento real (verificado: las 174 claves
# reales del Apéndice 8 no incluyen ninguna que empiece por "Z9"/"Z8") -- la
# base local puede tener ya la carga real, y `(code, level, valid_from)` es
# único.
NORMAL = "Z9"
SIN_NIVEL = "Z8"


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


@pytest.mark.integration
def test_load_anexo22_inserta_identificadores_de_pedimento(pg_session: Session) -> None:
    identifiers = [
        ParsedIdentifier(code=NORMAL, level="G"),
        ParsedIdentifier(code=SIN_NIVEL, level=None),
    ]

    n_offices, n_units, n_claves, n_regs, n_ids = load_anexo22(
        pg_session,
        offices=[],
        units=[],
        claves=[],
        regulations=[],
        identifiers=identifiers,
        content_hash=HASH,
        retrieved_at=datetime.now(UTC),
    )

    assert (n_offices, n_units, n_claves, n_regs, n_ids) == (0, 0, 0, 0, 2)
    filas = {
        row.code: row
        for row in pg_session.query(PedimentoIdentifier).filter(
            PedimentoIdentifier.code.in_((NORMAL, SIN_NIVEL))
        )
    }
    assert filas[NORMAL].level == "G"
    assert filas[SIN_NIVEL].level is None
    assert all(f.data_origin == "OFFICIAL" and f.content_hash == HASH for f in filas.values())


@pytest.mark.integration
def test_mismo_code_con_nivel_distinto_no_choca(pg_session: Session) -> None:
    """(code, level) es la llave -- no `code` solo (regresión real: "CF" G y
    "CF" P son entidades distintas en el documento)."""
    identifiers = [
        ParsedIdentifier(code=NORMAL, level="G"),
        ParsedIdentifier(code=NORMAL, level="P"),
    ]

    _, _, _, _, n_ids = load_anexo22(
        pg_session,
        offices=[],
        units=[],
        claves=[],
        regulations=[],
        identifiers=identifiers,
        content_hash=HASH,
        retrieved_at=datetime.now(UTC),
    )

    assert n_ids == 2
    niveles = {
        row.level
        for row in pg_session.query(PedimentoIdentifier).filter(PedimentoIdentifier.code == NORMAL)
    }
    assert niveles == {"G", "P"}
