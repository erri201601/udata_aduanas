"""Tests de integración de `ingestion.dof.load.load_identifier_requirements`.

Usa "Y9"/"K9" -- no existen en el documento real (mismo criterio que "Y9"/
"Y8" en `test_ingestion_dof_load_identificadores_texto.py`)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.regulatory import PedimentoIdentifierRequirement
from ingestion.dof.apendice_8_requisitos import ParsedIdentifierRequirement
from ingestion.dof.load import load_identifier_requirements
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "b2" * 32
CODIGO = "Y9"
CLAVE = "K9"


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


def test_carga_una_fila_nueva(pg_session: Session) -> None:
    requisitos = [ParsedIdentifierRequirement(CODIGO, CLAVE, "regla de prueba")]

    n = load_identifier_requirements(pg_session, requisitos=requisitos, content_hash=HASH)

    assert n == 1
    fila = (
        pg_session.query(PedimentoIdentifierRequirement)
        .filter_by(identifier_code=CODIGO, pedimento_key=CLAVE)
        .one()
    )
    assert fila.scope_note == "regla de prueba"
    assert fila.data_origin == "OFFICIAL"


def test_es_idempotente(pg_session: Session) -> None:
    requisitos = [ParsedIdentifierRequirement(CODIGO, CLAVE, None)]

    primera = load_identifier_requirements(pg_session, requisitos=requisitos, content_hash=HASH)
    segunda = load_identifier_requirements(pg_session, requisitos=requisitos, content_hash=HASH)

    assert primera == 1
    assert segunda == 0
