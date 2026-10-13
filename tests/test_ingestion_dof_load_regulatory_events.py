"""Tests de integración de `ingestion.dof.load.load_regulatory_events`
(§11 DOF, §43 Sprint 6)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.regulatory import RegulatoryEvent
from ingestion.dof.load import load_regulatory_events
from ingestion.dof.sumario import ParsedSumarioItem
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "c3" * 32
CODIGO_PRUEBA = "9999999"


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


def _item(**kw: object) -> ParsedSumarioItem:
    base: dict[str, object] = {
        "authority": "PODER EJECUTIVO SECRETARIA DE ECONOMIA",
        "description": "Decreto de prueba sobre comercio exterior.",
        "source_url": f"https://dof.gob.mx/nota_detalle.php?codigo={CODIGO_PRUEBA}&fecha=13/10/2026",
        "value_date": date(2026, 10, 13),
        "codigo": CODIGO_PRUEBA,
    }
    base.update(kw)
    return ParsedSumarioItem(**base)  # type: ignore[arg-type]


def test_carga_un_evento_nuevo(pg_session: Session) -> None:
    n = load_regulatory_events(pg_session, items=[_item()], content_hash=HASH)

    assert n == 1
    fila = pg_session.scalars(
        sa.select(RegulatoryEvent).where(
            RegulatoryEvent.source_url.like(f"%codigo={CODIGO_PRUEBA}%")
        )
    ).one()
    assert fila.data_origin == "OFFICIAL"
    assert fila.valid_from == date(2026, 10, 13)
    assert fila.affected_fraction_codes == []


def test_es_idempotente_por_source_url(pg_session: Session) -> None:
    items = [_item()]
    primera = load_regulatory_events(pg_session, items=items, content_hash=HASH)
    segunda = load_regulatory_events(pg_session, items=items, content_hash=HASH)

    assert primera == 1
    assert segunda == 0
