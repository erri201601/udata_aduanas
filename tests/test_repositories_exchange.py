"""Tests de `database.repositories.exchange.tasa_vigente`."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.repositories.exchange import tasa_vigente
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "f" * 64
DIVISA = "YYY"


@pytest.fixture
def pg_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
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


def _sembrar(session: Session, *, dia_desde: date, dia_hasta: date | None, tasa: str) -> None:
    from database.models.regulatory import ExchangeRate

    session.add(
        ExchangeRate(
            currency=DIVISA,
            rate=Decimal(tasa),
            data_origin="OFFICIAL",
            valid_from=dia_desde,
            valid_to=dia_hasta,
            source_url="https://ejemplo.invalido/prueba",
            content_hash=HASH,
            retrieved_at=datetime.now(UTC),
        )
    )
    session.flush()


def test_encuentra_la_fila_que_cubre_la_fecha(pg_session: Session) -> None:
    _sembrar(pg_session, dia_desde=date(2099, 6, 1), dia_hasta=date(2099, 6, 3), tasa="19.500000")

    assert tasa_vigente(pg_session, on_date=date(2099, 6, 2), currency=DIVISA) == Decimal(
        "19.500000"
    )


def test_un_fin_de_semana_usa_la_tasa_del_viernes(pg_session: Session) -> None:
    """valid_to abierto cubre el fin de semana hasta que llegue la siguiente."""
    _sembrar(pg_session, dia_desde=date(2099, 7, 3), dia_hasta=None, tasa="19.800000")

    assert tasa_vigente(pg_session, on_date=date(2099, 7, 5), currency=DIVISA) == Decimal(
        "19.800000"
    )


def test_sin_fila_que_cubra_la_fecha_es_none(pg_session: Session) -> None:
    _sembrar(pg_session, dia_desde=date(2099, 8, 1), dia_hasta=date(2099, 8, 1), tasa="20.000000")

    # Un día antes de que exista cualquier fila para esta divisa.
    assert tasa_vigente(pg_session, on_date=date(2099, 7, 31), currency=DIVISA) is None


def test_no_extrapola_mas_alla_de_un_valid_to_cerrado(pg_session: Session) -> None:
    _sembrar(pg_session, dia_desde=date(2099, 9, 1), dia_hasta=date(2099, 9, 1), tasa="21.000000")
    _sembrar(pg_session, dia_desde=date(2099, 9, 3), dia_hasta=None, tasa="21.500000")

    # 09-02 cae en el hueco entre las dos filas (cerrada la primera, abierta
    # la segunda hasta el 09-03) -- no se inventa cuál aplicaba.
    assert tasa_vigente(pg_session, on_date=date(2099, 9, 2), currency=DIVISA) is None
