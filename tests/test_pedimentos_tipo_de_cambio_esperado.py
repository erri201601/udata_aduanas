"""Tests de integración de `apps.api.routers.pedimentos._tipo_de_cambio_esperado`
— consumidor del FIX que faltaba (Erick, 6-oct): el Espejo ya convertía el
valor de la factura con el FIX, pero nadie comparaba
`pedimentos.exchange_rate` (lo DECLARADO) contra el FIX real de la fecha de
operación. `regulatory.exchange_rates` tenía 192 filas (PR #199) y ningún
módulo de `apps/` o `core/` las consultaba para esto.

Usa `currency="YZZ"` (no choca con las filas USD reales ya cargadas en esta
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

HASH = "f" * 64
DIVISA = "YZZ"


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
        "description": "Cable de acero",
        "declared_fraction_code": "73121099",
        "quantity": Decimal("10"),
        "country_of_origin": "CN",
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


def test_devuelve_el_fix_vigente_cuando_la_factura_es_otra_divisa(pg_session: Session) -> None:
    from apps.api.routers.pedimentos import _tipo_de_cambio_esperado

    _sembrar_tasa(pg_session, dia=date(2099, 6, 1), tasa="18.500000")
    partida = _partida(price_paid_currency=DIVISA)

    tasa = _tipo_de_cambio_esperado(pg_session, partida, date(2099, 6, 1))

    assert tasa == Decimal("18.500000")


def test_no_aplica_cuando_la_factura_ya_es_mxn(pg_session: Session) -> None:
    """Nada que convertir: `None` es «no aplica», no «coincide»."""
    from apps.api.routers.pedimentos import _tipo_de_cambio_esperado

    partida = _partida(price_paid_currency="MXN")

    tasa = _tipo_de_cambio_esperado(pg_session, partida, date(2099, 6, 1))

    assert tasa is None


def test_sin_tasa_cargada_para_esa_fecha_es_needs_validation(pg_session: Session) -> None:
    """Divisa/fecha sin ningún tipo de cambio sembrado -- no se inventa uno:
    `None`, la respuesta honesta (no se compara, no se afirma que coincida)."""
    from apps.api.routers.pedimentos import _tipo_de_cambio_esperado

    partida = _partida(price_paid_currency="XYW")

    tasa = _tipo_de_cambio_esperado(pg_session, partida, date(1999, 1, 1))

    assert tasa is None
