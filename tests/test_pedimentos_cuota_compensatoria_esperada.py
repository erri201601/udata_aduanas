"""Tests de integración de
`apps.api.routers.pedimentos._cuota_compensatoria_esperada` (ADR 0009) --
el consumidor que faltaba: `regulatory.compensatory_duties` se carga
(`ingestion.se.cuotas_compensatorias`) pero nadie la comparaba contra lo
declarado en la partida.

Usa `currency`/códigos que no chocan con los reales ya cargados en esta
base (fracción `99999999`, origen `ZZ`) salvo en los tests que
deliberadamente usan el caso real (cable de acero, China, `73121099`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models import Client, Invoice, InvoiceItem, PedimentoItem, Supplier
from database.models.regulatory import CompensatoryDuty
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "9" * 64
FRACCION = "99999999"


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


def _partida_con_proveedor(
    session: Session, *, legal_name: str, fraction_code: str = FRACCION, **kw: object
) -> PedimentoItem:
    cliente = Client(legal_name="Cliente de prueba", data_origin="SYNTHETIC")
    proveedor = Supplier(legal_name=legal_name, country="CN", data_origin="SYNTHETIC")
    session.add_all([cliente, proveedor])
    session.flush()

    factura = Invoice(
        client_id=cliente.id,
        supplier_id=proveedor.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        invoice_date=date(2026, 8, 1),
        currency="USD",
        total_amount=Decimal("1000.00"),
        total_amount_currency="USD",
        data_origin="SYNTHETIC",
    )
    session.add(factura)
    session.flush()

    partida_factura = InvoiceItem(
        invoice_id=factura.id,
        line_number=1,
        description="Cable de acero",
        quantity=Decimal("10"),
        unit_price=Decimal("100.00"),
        unit_price_currency="USD",
        line_total=Decimal("1000.00"),
        line_total_currency="USD",
        data_origin="SYNTHETIC",
    )
    session.add(partida_factura)
    session.flush()

    campos: dict[str, object] = {
        "line_number": 1,
        "description": "Cable de acero",
        "declared_fraction_code": fraction_code,
        "quantity": Decimal("10"),
        "country_of_origin": "CN",
        "data_origin": "SYNTHETIC",
        "invoice_item_id": partida_factura.id,
        "product_id": None,
    }
    campos.update(kw)
    return PedimentoItem(**campos)  # type: ignore[arg-type]


def _sembrar_cuota(session: Session, *, exporter_name: str | None, rate: str = "2.58") -> None:
    session.add(
        CompensatoryDuty(
            origin_country="CN",
            fraction_code=FRACCION,
            exporter_name=exporter_name,
            rate=Decimal(rate),
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


def test_aplica_y_calcula_el_monto_cuando_la_unidad_coincide(pg_session: Session) -> None:
    from apps.api.routers.pedimentos import _cuota_compensatoria_esperada

    _sembrar_cuota(pg_session, exporter_name=None)
    partida = _partida_con_proveedor(
        pg_session,
        legal_name="Cualquier Exportador SA",
        quantity=Decimal("10"),
        commercial_unit="1",  # "1" = Kilo, ver regulatory.units_of_measure
    )

    aplica, monto = _cuota_compensatoria_esperada(pg_session, partida, date(2026, 8, 3))

    assert aplica is True
    assert monto == Decimal("25.80")  # 2.58 * 10


def test_aplica_pero_sin_monto_cuando_la_unidad_no_coincide(pg_session: Session) -> None:
    """Caso real del corpus: el cable se declara en metro lineal ("3"), no
    en kilogramo ("1") -- no se inventa un factor de conversión."""
    from apps.api.routers.pedimentos import _cuota_compensatoria_esperada

    _sembrar_cuota(pg_session, exporter_name=None)
    partida = _partida_con_proveedor(
        pg_session,
        legal_name="Cualquier Exportador SA",
        commercial_unit="3",  # "3" = Metro lineal
    )

    aplica, monto = _cuota_compensatoria_esperada(pg_session, partida, date(2026, 8, 3))

    assert aplica is True
    assert monto is None


def test_sin_cuota_cargada_para_esa_combinacion_es_needs_validation(pg_session: Session) -> None:
    """Sin fila en `CompensatoryDuty` para este origen/fracción: "no se
    sabe", no "no aplica"."""
    from apps.api.routers.pedimentos import _cuota_compensatoria_esperada

    partida = _partida_con_proveedor(
        pg_session, legal_name="Cualquier Exportador SA", fraction_code="12345678"
    )

    aplica, monto = _cuota_compensatoria_esperada(pg_session, partida, date(2026, 8, 3))

    assert aplica is None
    assert monto is None


def test_exportador_nombrado_coincide_por_nombre_normalizado(pg_session: Session) -> None:
    """La resolución nombra a un exportador con su propia tasa; el nombre
    del proveedor coincide salvo mayúsculas/puntuación -- SÍ debe usarse,
    no la residual."""
    from apps.api.routers.pedimentos import _cuota_compensatoria_esperada

    _sembrar_cuota(pg_session, exporter_name="ORIENTAL TECHNICAL SUPPLY CO LTD", rate="9.00")
    _sembrar_cuota(pg_session, exporter_name=None, rate="2.58")
    partida = _partida_con_proveedor(
        pg_session,
        legal_name="Oriental Technical Supply Co. Ltd.",
        commercial_unit="1",
        quantity=Decimal("10"),
    )

    aplica, monto = _cuota_compensatoria_esperada(pg_session, partida, date(2026, 8, 3))

    assert aplica is True
    assert monto == Decimal("90.00")  # 9.00 * 10, NO la residual de 2.58


def test_exportador_sin_coincidencia_usa_la_tasa_residual(pg_session: Session) -> None:
    """El proveedor NO es el exportador nombrado -- nunca una coincidencia
    aproximada: se aplica la tasa de "las demás" (decisión de Persona 1,
    6-oct)."""
    from apps.api.routers.pedimentos import _cuota_compensatoria_esperada

    _sembrar_cuota(pg_session, exporter_name="OTRO EXPORTADOR SA", rate="9.00")
    _sembrar_cuota(pg_session, exporter_name=None, rate="2.58")
    partida = _partida_con_proveedor(
        pg_session,
        legal_name="Oriental Technical Supply Co. Ltd.",
        commercial_unit="1",
        quantity=Decimal("10"),
    )

    aplica, monto = _cuota_compensatoria_esperada(pg_session, partida, date(2026, 8, 3))

    assert aplica is True
    assert monto == Decimal("25.80")  # la residual, no la de "OTRO EXPORTADOR SA"
