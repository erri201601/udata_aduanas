"""Tests de integración de
`ingestion.se.load.cargar_cuotas_compensatorias` (ADR 0009)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.regulatory import CompensatoryDuty
from ingestion.se.cuotas_compensatorias import ParsedCompensatoryDuty
from ingestion.se.load import cargar_cuotas_compensatorias
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "8" * 64
FRACCION = "88888801"


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


def _fila(**kw: object) -> ParsedCompensatoryDuty:
    base: dict[str, object] = {
        "origin_country": "ZZ",
        "fraction_code": FRACCION,
        "exporter_name": None,
        "rate": "1.23",
        "rate_currency": "USD",
        "rate_unit": "KG",
        "valid_from": date(2026, 1, 1),
        "valid_to": date(2030, 1, 1),
        "scope_note": "prueba",
    }
    base.update(kw)
    return ParsedCompensatoryDuty(**base)  # type: ignore[arg-type]


def test_carga_las_filas_que_faltan(pg_session: Session) -> None:
    n = cargar_cuotas_compensatorias(
        pg_session,
        [_fila()],
        content_hash=HASH,
        source_url="https://ejemplo.invalido/prueba",
        source_document="Resolución de prueba",
    )

    assert n == 1
    fila = pg_session.scalars(
        sa.select(CompensatoryDuty).where(CompensatoryDuty.fraction_code == FRACCION)
    ).one()
    assert fila.rate == Decimal("1.23")
    assert fila.data_origin == "OFFICIAL"


def test_es_idempotente(pg_session: Session) -> None:
    filas = [_fila()]
    primera = cargar_cuotas_compensatorias(
        pg_session,
        filas,
        content_hash=HASH,
        source_url="https://ejemplo.invalido/prueba",
        source_document="Resolución de prueba",
    )
    segunda = cargar_cuotas_compensatorias(
        pg_session,
        filas,
        content_hash=HASH,
        source_url="https://ejemplo.invalido/prueba",
        source_document="Resolución de prueba",
    )

    assert primera == 1
    assert segunda == 0


def test_distingue_exportador_nombrado_de_la_residual(pg_session: Session) -> None:
    filas = [
        _fila(exporter_name="EXPORTADOR NOMBRADO SA", rate="9.00"),
        _fila(exporter_name=None, rate="1.23"),
    ]

    n = cargar_cuotas_compensatorias(
        pg_session,
        filas,
        content_hash=HASH,
        source_url="https://ejemplo.invalido/prueba",
        source_document="Resolución de prueba",
    )

    assert n == 2
    cargadas = pg_session.scalars(
        sa.select(CompensatoryDuty).where(CompensatoryDuty.fraction_code == FRACCION)
    ).all()
    assert {f.exporter_name for f in cargadas} == {"EXPORTADOR NOMBRADO SA", None}
