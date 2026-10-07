"""Tests de integración de
`apps.evaluacion.deteccion_26._cuotas_compensatorias_ciertas` (ADR 0009):
las partidas con una cuota compensatoria real vigente no deben contar
como falsos positivos -- mismo criterio que `_fichas_recortadas_a_proposito`/
`_fracciones_que_un_dictamen_contradice`, por el mismo motivo que ya costó
diez falsos positivos en el #200.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models import Client, Pedimento, PedimentoItem
from database.models.regulatory import CompensatoryDuty
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "7" * 64
FRACCION = "77777701"


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


def _pedimento_con_partida(
    session: Session, *, fraction_code: str = FRACCION, origin: str = "CN"
) -> tuple[uuid.UUID, PedimentoItem]:
    cliente = Client(legal_name="Cliente de prueba", data_origin="SYNTHETIC")
    session.add(cliente)
    session.flush()

    pedimento = Pedimento(
        client_id=cliente.id,
        pedimento_number=f"26{uuid.uuid4().int % 10**19:019d}"[:21],
        trade_flow="IMPORT",
        operation_date=date(2026, 8, 3),
        currency="MXN",
        data_origin="SYNTHETIC",
    )
    session.add(pedimento)
    session.flush()

    partida = PedimentoItem(
        pedimento_id=pedimento.id,
        line_number=1,
        description="Cable de acero",
        declared_fraction_code=fraction_code,
        quantity=Decimal("10"),
        country_of_origin=origin,
        data_origin="SYNTHETIC",
    )
    session.add(partida)
    session.flush()
    return pedimento.id, partida


def _sembrar_cuota(session: Session) -> None:
    session.add(
        CompensatoryDuty(
            origin_country="CN",
            fraction_code=FRACCION,
            exporter_name=None,
            rate=Decimal("2.58"),
            rate_currency="USD",
            rate_unit="KG",
            data_origin="OFFICIAL",
            valid_from=date(2024, 12, 17),
            valid_to=date(2029, 12, 17),
            source_url="https://ejemplo.invalido/prueba",
            content_hash=HASH,
            retrieved_at=datetime.now(UTC),
        )
    )
    session.flush()


def test_una_partida_con_cuota_real_no_cuenta_como_falso_positivo(pg_session: Session) -> None:
    from apps.evaluacion.deteccion_26 import (
        DETECTOR_DE_CUOTA_COMPENSATORIA,
        _cuotas_compensatorias_ciertas,
    )

    _sembrar_cuota(pg_session)
    pedimento_id, partida = _pedimento_con_partida(pg_session)

    ciertas = _cuotas_compensatorias_ciertas(
        pg_session, {partida.id: partida}, {pedimento_id: date(2026, 8, 3)}
    )

    assert ciertas == {(str(partida.id), DETECTOR_DE_CUOTA_COMPENSATORIA)}


def test_sin_cuota_cargada_no_hay_nada_que_excluir(pg_session: Session) -> None:
    from apps.evaluacion.deteccion_26 import _cuotas_compensatorias_ciertas

    pedimento_id, partida = _pedimento_con_partida(pg_session, fraction_code="00000000")

    ciertas = _cuotas_compensatorias_ciertas(
        pg_session, {partida.id: partida}, {pedimento_id: date(2026, 8, 3)}
    )

    assert ciertas == set()


def test_fuera_de_la_ventana_de_vigencia_no_cuenta(pg_session: Session) -> None:
    """La misma combinación, pero la operación es ANTERIOR a que la cuota
    entrara en vigor (17-dic-2024) -- no se afirma que aplique."""
    from apps.evaluacion.deteccion_26 import _cuotas_compensatorias_ciertas

    _sembrar_cuota(pg_session)
    cliente = Client(legal_name="Cliente de prueba", data_origin="SYNTHETIC")
    pg_session.add(cliente)
    pg_session.flush()
    pedimento = Pedimento(
        client_id=cliente.id,
        pedimento_number=f"26{uuid.uuid4().int % 10**19:019d}"[:21],
        trade_flow="IMPORT",
        operation_date=date(2020, 1, 1),
        currency="MXN",
        data_origin="SYNTHETIC",
    )
    pg_session.add(pedimento)
    pg_session.flush()
    partida = PedimentoItem(
        pedimento_id=pedimento.id,
        line_number=1,
        description="Cable de acero",
        declared_fraction_code=FRACCION,
        quantity=Decimal("10"),
        country_of_origin="CN",
        data_origin="SYNTHETIC",
    )
    pg_session.add(partida)
    pg_session.flush()

    ciertas = _cuotas_compensatorias_ciertas(
        pg_session, {partida.id: partida}, {pedimento.id: date(2020, 1, 1)}
    )

    assert ciertas == set()
