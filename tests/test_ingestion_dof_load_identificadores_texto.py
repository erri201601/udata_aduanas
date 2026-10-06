"""Tests de integración de `ingestion.dof.load.add_missing_identifier_text` y
`load_identifier_chunks` (Apéndice 8: `label`/`supuestos_de_aplicacion`,
decisión de Persona 1, 6-oct).

Usa "Y9"/"Y8" -- no existen en el documento real (mismo criterio que "Z9"/
"Z8" en `test_ingestion_dof_load_anexo22.py`, verificado: ninguna de las
172 claves reales empieza por esas letras).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.regulatory import LegalChunkRecord, PedimentoIdentifier
from ingestion.dof.anexo22 import ParsedIdentifier
from ingestion.dof.load import add_missing_identifier_text, load_identifier_chunks
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "a1" * 32
CON_NIVEL = "Y9"
SIN_NIVEL = "Y8"


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


def test_agrega_una_clave_nueva_que_no_existia(pg_session: Session) -> None:
    identifiers = [
        ParsedIdentifier(
            code=CON_NIVEL,
            level="G",
            label="Etiqueta de prueba.",
            supuestos_de_aplicacion="Supuesto de prueba.",
        )
    ]

    creadas, enriquecidas = add_missing_identifier_text(
        pg_session, identifiers=identifiers, content_hash=HASH
    )

    assert creadas == 1
    assert enriquecidas == 0
    fila = pg_session.query(PedimentoIdentifier).filter_by(code=CON_NIVEL, level="G").one()
    assert fila.label == "Etiqueta de prueba."
    assert fila.supuestos_de_aplicacion == "Supuesto de prueba."
    assert fila.data_origin == "OFFICIAL"


def test_enriquece_una_clave_ya_cargada_sin_texto(pg_session: Session) -> None:
    pg_session.add(
        PedimentoIdentifier(
            code=SIN_NIVEL,
            level=None,
            label=None,
            supuestos_de_aplicacion=None,
            data_origin="OFFICIAL",
            valid_from=datetime.now(UTC).date(),
            source_url="https://ejemplo.invalido/prueba",
            content_hash=HASH,
            retrieved_at=datetime.now(UTC),
        )
    )
    pg_session.flush()

    identifiers = [
        ParsedIdentifier(
            code=SIN_NIVEL,
            level=None,
            label="Ya con texto.",
            supuestos_de_aplicacion="Ya con supuesto.",
        )
    ]
    creadas, enriquecidas = add_missing_identifier_text(
        pg_session, identifiers=identifiers, content_hash=HASH
    )

    assert creadas == 0
    assert enriquecidas == 1
    fila = pg_session.query(PedimentoIdentifier).filter_by(code=SIN_NIVEL).one()
    assert fila.label == "Ya con texto."


def test_es_idempotente_no_sobrescribe_texto_ya_enriquecido(pg_session: Session) -> None:
    identifiers = [
        ParsedIdentifier(
            code=CON_NIVEL,
            level="P",
            label="Primera versión.",
            supuestos_de_aplicacion="Primer supuesto.",
        )
    ]
    add_missing_identifier_text(pg_session, identifiers=identifiers, content_hash=HASH)

    otra_version = [
        ParsedIdentifier(
            code=CON_NIVEL,
            level="P",
            label="Segunda versión, no debería aplicarse.",
            supuestos_de_aplicacion="Otro.",
        )
    ]
    creadas, enriquecidas = add_missing_identifier_text(
        pg_session, identifiers=otra_version, content_hash=HASH
    )

    assert creadas == 0
    assert enriquecidas == 0
    fila = pg_session.query(PedimentoIdentifier).filter_by(code=CON_NIVEL, level="P").one()
    assert fila.label == "Primera versión."


def test_load_identifier_chunks_crea_un_chunk_citable(pg_session: Session) -> None:
    identifiers = [
        ParsedIdentifier(
            code=CON_NIVEL,
            level="G",
            label="Etiqueta citable.",
            supuestos_de_aplicacion="Supuesto citable.",
        )
    ]

    n = load_identifier_chunks(pg_session, identifiers=identifiers, content_hash=HASH)

    assert n == 1
    chunk = (
        pg_session.query(LegalChunkRecord)
        .filter(LegalChunkRecord.article == f"Apéndice 8, clave {CON_NIVEL} (nivel G)")
        .one()
    )
    assert "Etiqueta citable." in chunk.text
    assert "Supuesto citable." in chunk.text
    assert chunk.data_origin == "OFFICIAL"


def test_load_identifier_chunks_distingue_un_mismo_codigo_con_dos_niveles(
    pg_session: Session,
) -> None:
    """Regresión real: 6 claves del documento repiten código con nivel G Y
    P, cada una con su propio supuesto (caso real: "CF", página 147) -- sin
    el nivel en el `article`, la segunda chocaba contra la primera en el
    chequeo de idempotencia y su supuesto nunca entraba al RAG."""
    identifiers = [
        ParsedIdentifier(
            code=CON_NIVEL, level="G", label="Label G.", supuestos_de_aplicacion="Supuesto G."
        ),
        ParsedIdentifier(
            code=CON_NIVEL, level="P", label="Label P.", supuestos_de_aplicacion="Supuesto P."
        ),
    ]

    n = load_identifier_chunks(pg_session, identifiers=identifiers, content_hash=HASH)

    assert n == 2
    articles = {
        a
        for (a,) in pg_session.query(LegalChunkRecord.article).filter(
            LegalChunkRecord.article.like(f"Apéndice 8, clave {CON_NIVEL}%")
        )
    }
    assert articles == {
        f"Apéndice 8, clave {CON_NIVEL} (nivel G)",
        f"Apéndice 8, clave {CON_NIVEL} (nivel P)",
    }


def test_load_identifier_chunks_salta_las_que_no_tienen_texto(pg_session: Session) -> None:
    identifiers = [
        ParsedIdentifier(code=CON_NIVEL, level="G", label=None, supuestos_de_aplicacion=None)
    ]

    n = load_identifier_chunks(pg_session, identifiers=identifiers, content_hash=HASH)

    assert n == 0


def test_load_identifier_chunks_es_idempotente(pg_session: Session) -> None:
    identifiers = [
        ParsedIdentifier(
            code=CON_NIVEL, level="G", label="Etiqueta.", supuestos_de_aplicacion="Supuesto."
        )
    ]

    primera = load_identifier_chunks(pg_session, identifiers=identifiers, content_hash=HASH)
    segunda = load_identifier_chunks(pg_session, identifiers=identifiers, content_hash=HASH)

    assert primera == 1
    assert segunda == 0
