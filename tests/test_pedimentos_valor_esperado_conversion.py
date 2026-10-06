"""Tests de integración de `apps.api.routers.pedimentos._valor_esperado`
convirtiendo a MXN con el FIX real (`ingestion.banxico`, 2026-10-06).

Antes de esto, una factura en una divisa distinta de MXN SIEMPRE devolvía
su propia divisa sin convertir, y `core/shadow/compare.py` reportaba
"divisa distinta" en cada partida real del corpus (invoices 100% USD,
pedimentos 100% MXN) — nunca llegaba a comparar el monto.

Usa `currency="ZZ"` (no choca con las filas USD reales ya cargadas en esta
base) para poder sembrar un tipo de cambio exacto y medible.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models import PedimentoItem
from database.models.regulatory import ExchangeRate
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "e" * 64
DIVISA = "ZZZ"


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


def _partida(**kw: object) -> PedimentoItem:
    campos: dict[str, object] = {
        "line_number": 1,
        "description": "Tubo de acero",
        "declared_fraction_code": "73051291",
        "quantity": Decimal("10"),
        "country_of_origin": "BR",
        "data_origin": "SYNTHETIC",
        "invoice_item_id": uuid.uuid4(),
        "product_id": None,
    }
    campos.update(kw)
    return PedimentoItem(**campos)  # type: ignore[arg-type]


def _sembrar_tasa(session: Session, *, dia: date, tasa: str) -> None:
    session.add(
        ExchangeRate(
            currency=DIVISA,
            rate=Decimal(tasa),
            data_origin="OFFICIAL",
            valid_from=dia,
            valid_to=dia,
            source_url="https://ejemplo.invalido/prueba",
            content_hash=HASH,
            retrieved_at=datetime.now(UTC),
        )
    )
    session.flush()


def test_convierte_a_mxn_con_la_tasa_vigente(pg_session: Session) -> None:
    from apps.api.routers.pedimentos import _valor_esperado

    _sembrar_tasa(pg_session, dia=date(2099, 5, 1), tasa="20.000000")
    partida = _partida(
        price_paid=Decimal("1000.00"),
        incrementables=Decimal("50.00"),
        price_paid_currency=DIVISA,
        incrementables_currency=DIVISA,
    )

    valor, moneda = _valor_esperado(pg_session, partida, date(2099, 5, 1))

    assert moneda == "MXN"
    assert valor == Decimal("21000.000000")  # (1000 + 50) * 20


def test_sin_tasa_cargada_para_esa_fecha_es_needs_validation(pg_session: Session) -> None:
    """Divisa/fecha sin ningún tipo de cambio sembrado -- no se inventa uno
    ni se compara sin convertir: `None`, la respuesta honesta."""
    from apps.api.routers.pedimentos import _valor_esperado

    partida = _partida(
        price_paid=Decimal("1000.00"),
        incrementables=Decimal("50.00"),
        price_paid_currency="YY",
        incrementables_currency="YY",
    )

    valor, moneda = _valor_esperado(pg_session, partida, date(1999, 1, 1))

    assert valor is None
    assert moneda is None
