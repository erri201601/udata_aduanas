"""Tests de integración del cargador del corpus espejo V1 (Persona 1, 22-sep-2026).

`integration` — necesitan PostgreSQL local; se saltan si no hay conexión.
Regresión de dos bugs reales de la primera versión del cargador:

1. `Product` se creaba uno por PARTIDA en vez de uno por FICHA DE CATÁLOGO
   (`product_id`) — con eso, `INCONSISTENT_SKU_CLASSIFICATION` ("el mismo
   SKU clasificado distinto en dos pedimentos") no podía existir, porque
   cada partida tenía su propio producto aislado.
2. `ProductDna.summary` se llenaba con `classification_reason` (el motivo
   de por qué se puede o no clasificar) en vez de la descripción comercial
   de la partida.

Cada test corre dentro de una transacción que se revierte al final.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from ingestion.sintetico.corpus_espejo import (
    ParsedCorpus,
    ParsedPartida,
    ParsedPedimento,
    ParsedProductSpec,
)
from ingestion.sintetico.load import load_corpus
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


@pytest.fixture
def pg_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Sesión contra el Postgres local. Salta el test si no hay conexión.

    Mismo patrón que `tests/test_canonical_model.py::pg_session`.
    """
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


def test_load_corpus_comparte_product_entre_dos_pedimentos_distintos(
    pg_session: Session,
) -> None:
    """Regresión: el mismo `product_id` en dos pedimentos distintos debe
    apuntar al MISMO `Product` — si no, `INCONSISTENT_SKU_CLASSIFICATION`
    no se puede detectar."""
    spec_p001 = ParsedProductSpec(
        id="P901", name="Producto de prueba", description="Descripción de catálogo", spec={"x": 1}
    )
    corpus = ParsedCorpus(
        pedimentos=[
            _pedimento(
                "DOC_A",
                "26 00 0000 6000001",
                partidas=[_partida("001", product_id="P901", descripcion="desc A", spec={"x": 1})],
            ),
            _pedimento(
                "DOC_B",
                "26 00 0000 6000002",
                partidas=[_partida("001", product_id="P901", descripcion="desc B", spec={"x": 1})],
            ),
        ],
        product_specs={"P901": spec_p001},
    )

    load_corpus(pg_session, corpus, seed=1)
    pg_session.flush()

    from database.models.operational import Product

    productos = pg_session.query(Product).filter_by(sku="P901").all()
    assert len(productos) == 1, "debe existir un solo Product para P901, no uno por partida"


def test_load_corpus_product_dna_summary_es_la_descripcion_comercial(
    pg_session: Session,
) -> None:
    """Regresión: `summary` viene de `commercial_description`, nunca de
    `classification_reason`."""
    spec_p002 = ParsedProductSpec(
        id="P902", name="Otro producto", description="Otra descripción", spec={"y": 2}
    )
    corpus = ParsedCorpus(
        pedimentos=[
            _pedimento(
                "DOC_C",
                "26 00 0000 6000003",
                partidas=[
                    _partida(
                        "001",
                        product_id="P902",
                        descripcion="TUBERIA DE PRUEBA DESCRIPCION COMERCIAL",
                        spec={"y": 2},
                    )
                ],
            )
        ],
        product_specs={"P902": spec_p002},
    )

    load_corpus(pg_session, corpus, seed=1)
    pg_session.flush()

    from database.models.intelligence import ProductDna
    from database.models.operational import Product

    producto = pg_session.query(Product).filter_by(sku="P902").one()
    dna = (
        pg_session.query(ProductDna)
        .filter_by(product_id=producto.id)
        .order_by(ProductDna.version.desc())
        .first()
    )
    assert dna is not None
    assert dna.summary == "TUBERIA DE PRUEBA DESCRIPCION COMERCIAL"
    assert "clasificacion" not in dna.summary.lower()
    assert "contrastar" not in dna.summary.lower()
