"""Tests de integración del COVE en el cargador del corpus espejo V1.

Antes de esta tarea, `load_corpus` creaba Client/Supplier/Invoice/
InvoiceItem por pedimento pero nunca un `Cove` -- 0 en el escenario aunque
el modelo ya existía desde el Canonical Model. Mismo patrón de fixtures que
`tests/test_ingestion_sintetico_load.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from database.models.operational import Cove, Invoice
from ingestion.sintetico.corpus_espejo import (
    ParsedCorpus,
    ParsedPartida,
    ParsedPedimento,
    ParsedProductSpec,
)
from ingestion.sintetico.load import add_missing_coves, delete_scenario_data, load_corpus
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


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
        get_settings.cache_clear()


def _partida(
    sec: str, *, product_id: str, descripcion: str, spec: dict[str, object]
) -> ParsedPartida:
    campos = {
        "fraccion": "76151002",
        "nico": "01",
        "umc": "3",
        "umt": "1",
        "cantidad_umc": 1,
        "cantidad_umt": 1,
        "igi_rate": 0.15,
        "iva_rate": 0.16,
        "precio_pagado_mxn": 100,
        "incrementables_mxn": 0,
        "valor_aduana_mxn": 100,
        "dta_mxn": 1,
        "igi_mxn": 15,
        "iva_base_mxn": 116,
        "iva_mxn": 19,
        "pais_origen": "CHN",
    }
    return ParsedPartida(
        sec=sec,
        product_id=product_id,
        commercial_description=descripcion,
        technical_spec=spec,
        classification_evaluable=True,
        classification_reason="Ficha tecnica suficiente para contrastar la clasificacion.",
        expected=dict(campos),
        observed=dict(campos),
        anomalies=[],
    )


def _pedimento(
    document_id: str, pedimento_number: str, *, partidas: list[ParsedPartida]
) -> ParsedPedimento:
    return ParsedPedimento(
        document_id=document_id,
        is_simulation=True,
        pedimento_number=pedimento_number,
        operation="IMP",
        pedimento_key="A1",
        regime="IMD",
        exchange_rate=Decimal("18.00"),
        entry_customs="470",
        date_entry=date(2026, 8, 1),
        date_payment=date(2026, 8, 2),
        importer_rfc=f"SIM{document_id}",
        importer_name=f"IMPORTADORA {document_id}",
        importer_address="AV. DATOS DE PRUEBA 1",
        provider_name="PROVEEDOR DE PRUEBA",
        provider_address="1 TEST ROAD",
        provider_country="CHN",
        provider_incoterm="CIF",
        provider_currency="USD",
        totals_valor_aduana_mxn=Decimal("100") * len(partidas),
        parts=partidas,
    )


def _corpus(document_id: str, pedimento_number: str) -> ParsedCorpus:
    spec: dict[str, object] = {"x": 1}
    return ParsedCorpus(
        pedimentos=[
            _pedimento(
                document_id,
                pedimento_number,
                partidas=[_partida("001", product_id="P901", descripcion="desc", spec=spec)],
            )
        ],
        product_specs={
            "P901": ParsedProductSpec(
                id="P901", name="Producto de prueba", description="desc", spec=spec
            )
        },
    )


def test_load_corpus_crea_un_cove_por_pedimento(pg_session: Session) -> None:
    corpus = _corpus("DOC_COVE_A", "26 00 0000 7000001")

    reporte = load_corpus(pg_session, corpus)

    assert reporte.coves_creados == 1
    invoice = pg_session.query(Invoice).filter_by(invoice_number="DOC_COVE_A").one()
    cove = pg_session.query(Cove).filter_by(invoice_id=invoice.id).one()
    assert cove.cove_number == "COVE-DOC_COVE_A"
    assert cove.issued_at == date(2026, 8, 1)
    assert cove.data_origin == "SYNTHETIC"


def test_load_corpus_no_duplica_cove_en_una_segunda_corrida(pg_session: Session) -> None:
    corpus = _corpus("DOC_COVE_B", "26 00 0000 7000002")
    load_corpus(pg_session, corpus)

    reporte2 = load_corpus(pg_session, corpus)

    assert reporte2.pedimentos_saltados == 1
    assert reporte2.coves_creados == 0
    invoice = pg_session.query(Invoice).filter_by(invoice_number="DOC_COVE_B").one()
    assert pg_session.query(Cove).filter_by(invoice_id=invoice.id).count() == 1


def test_add_missing_coves_rellena_una_carga_anterior_sin_cove(pg_session: Session) -> None:
    """Simula el estado real antes de esta tarea: pedimento/factura ya
    cargados, sin Cove -- `add_missing_coves` lo agrega sin tocar nada más."""
    corpus = _corpus("DOC_COVE_C", "26 00 0000 7000003")
    load_corpus(pg_session, corpus)
    invoice = pg_session.query(Invoice).filter_by(invoice_number="DOC_COVE_C").one()
    borrado = pg_session.query(Cove).filter_by(invoice_id=invoice.id).delete()
    assert borrado == 1
    pg_session.flush()

    creados = add_missing_coves(pg_session, corpus)

    assert creados == 1
    assert pg_session.query(Cove).filter_by(invoice_id=invoice.id).count() == 1


def test_add_missing_coves_es_idempotente(pg_session: Session) -> None:
    corpus = _corpus("DOC_COVE_D", "26 00 0000 7000004")
    load_corpus(pg_session, corpus)

    creados = add_missing_coves(pg_session, corpus)

    assert creados == 0


def test_delete_scenario_data_borra_el_cove(pg_session: Session) -> None:
    corpus = _corpus("DOC_COVE_E", "26 00 0000 7000005")
    load_corpus(pg_session, corpus)

    delete_scenario_data(pg_session)

    assert pg_session.query(Cove).filter_by(cove_number="COVE-DOC_COVE_E").count() == 0
