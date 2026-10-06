"""Tests de integración de `ingestion.banxico.load.load_exchange_rates`
contra el Postgres local.

Usa `currency="ZZ"` (no es ISO real, no choca con las filas USD ya
cargadas por el CLI en esta misma base) para poder borrar limpio y medir
exacto, igual que el resto de tests de carga de esta sesión.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.regulatory import ExchangeRate
from ingestion.banxico.fix import ParsedExchangeRate
from ingestion.banxico.load import load_exchange_rates
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "d" * 64
DIVISA = "ZZ"


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


def _fila(d: date, valor: str) -> ParsedExchangeRate:
    return ParsedExchangeRate(currency=DIVISA, rate_date=d, rate=Decimal(valor))


def test_inserta_y_encadena_la_vigencia(pg_session: Session) -> None:
    filas = [
        _fila(date(2099, 1, 2), "20.000000"),  # viernes (ficticio)
        _fila(date(2099, 1, 5), "20.100000"),  # el siguiente hábil -- cierra al anterior
        _fila(date(2099, 1, 6), "20.200000"),
    ]

    n = load_exchange_rates(pg_session, rates=filas, content_hash=HASH)
    assert n == 3

    cargadas = {
        r.valid_from: (r.valid_to, r.rate)
        for r in pg_session.query(ExchangeRate).filter_by(currency=DIVISA).all()
    }
    assert cargadas[date(2099, 1, 2)] == (date(2099, 1, 4), Decimal("20.000000"))
    assert cargadas[date(2099, 1, 5)] == (date(2099, 1, 5), Decimal("20.100000"))
    assert cargadas[date(2099, 1, 6)] == (None, Decimal("20.200000"))


def test_es_idempotente(pg_session: Session) -> None:
    filas = [_fila(date(2099, 2, 2), "21.000000")]

    primera = load_exchange_rates(pg_session, rates=filas, content_hash=HASH)
    segunda = load_exchange_rates(pg_session, rates=filas, content_hash=HASH)

    assert primera == 1
    assert segunda == 0
    assert (
        pg_session.query(ExchangeRate)
        .filter_by(currency=DIVISA, valid_from=date(2099, 2, 2))
        .count()
        == 1
    )


def test_desordenadas_igual_encadenan_bien(pg_session: Session) -> None:
    """El cargador ordena por fecha antes de cerrar vigencias -- no importa
    en qué orden lleguen las filas parseadas."""
    filas = [
        _fila(date(2099, 3, 6), "22.300000"),
        _fila(date(2099, 3, 2), "22.000000"),
        _fila(date(2099, 3, 5), "22.100000"),
    ]

    load_exchange_rates(pg_session, rates=filas, content_hash=HASH)

    fila_2 = (
        pg_session.query(ExchangeRate).filter_by(currency=DIVISA, valid_from=date(2099, 3, 2)).one()
    )
    assert fila_2.valid_to == date(2099, 3, 4)


def test_data_origin_y_content_hash(pg_session: Session) -> None:
    load_exchange_rates(pg_session, rates=[_fila(date(2099, 4, 1), "23.000000")], content_hash=HASH)
    fila = (
        pg_session.query(ExchangeRate).filter_by(currency=DIVISA, valid_from=date(2099, 4, 1)).one()
    )
    assert fila.data_origin == "OFFICIAL"
    assert fila.content_hash == HASH
    assert fila.source_id is not None
    assert isinstance(fila.retrieved_at, datetime)
    assert fila.retrieved_at.tzinfo is not None
