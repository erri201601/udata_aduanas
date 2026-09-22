"""Tests de integración del cargador del corpus espejo V1 (Persona 1, 22-sep-2026).

`integration` — necesitan PostgreSQL local; se saltan si no hay conexión.
Regresión de dos bugs reales:

1. `ProductDna.summary` se llenaba con `classification_reason` (el motivo
   de por qué se puede o no clasificar) en vez de la descripción comercial
   de la partida.
2. Un intento posterior de compartir un solo `Product` por `product_id` de
   catálogo (para habilitar `INCONSISTENT_SKU_CLASSIFICATION`) introdujo un
   bug peor: `apps/api/dna.py` resuelve la ficha vigente de un producto con
   `is_current=True`, y con `Product` compartido cada partida crea una
   versión nueva sin cerrar las anteriores — todas las partidas de ese
   producto terminan leyendo la MISMA ficha (la última cargada), y las 21
   con `classification_evaluable=false` reciben una ficha completa ajena.
   Se revirtió a un `Product` por partida, con `model` guardando el
   `product_id` de catálogo para no perder esa identidad.

Cada test corre dentro de una transacción que se revierte al final.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from ingestion.sintetico.corpus_espejo import (
    ParsedAnomaly,
    ParsedCorpus,
    ParsedPartida,
    ParsedPedimento,
    ParsedProductSpec,
)
from ingestion.sintetico.load import fix_missing_information, load_corpus
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
    sec: str,
    *,
    product_id: str,
    descripcion: str,
    spec: dict[str, object],
    anomalies: list[ParsedAnomaly] | None = None,
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
        anomalies=anomalies or [],
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


def test_load_corpus_un_product_por_partida_con_identidad_de_catalogo_visible(
    pg_session: Session,
) -> None:
    """Regresión (Persona 1, 22-sep-2026, revirtiendo un intento anterior de
    compartir `Product`): el mismo `product_id` en dos pedimentos distintos
    crea DOS `Product` separados -- uno por partida, cada uno con su propia
    `ProductDna` -- porque `apps/api/dna.py` resuelve la ficha vigente por
    `product_id` con `is_current=True`, y un `Product` compartido dejaría
    todas las partidas de ese producto leyendo la MISMA ficha (la última
    cargada). La identidad de catálogo no se pierde: ambos `Product` llevan
    el mismo `model` (el `product_id` del corpus)."""
    spec = ParsedProductSpec(
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
        product_specs={"P901": spec},
    )

    load_corpus(pg_session, corpus, seed=1)
    pg_session.flush()

    from database.models.operational import Product

    productos = pg_session.query(Product).filter_by(model="P901").all()
    assert len(productos) == 2, "un Product por partida, no uno compartido"
    assert {p.sku for p in productos} == {"DOC_A-001", "DOC_B-001"}
    assert all(p.model == "P901" for p in productos)


def test_load_corpus_cada_product_tiene_exactamente_una_dna_vigente(
    pg_session: Session,
) -> None:
    """Invariante que impide en la raíz el bug real: con un `Product` por
    partida, cada `Product` sólo puede tener UNA `ProductDna`, así que
    `is_current=True` nunca puede resolver ambiguo entre dos partidas."""
    spec = ParsedProductSpec(
        id="P903", name="Producto de prueba 2", description="Descripción", spec={"z": 1}
    )
    corpus = ParsedCorpus(
        pedimentos=[
            _pedimento(
                "DOC_D",
                "26 00 0000 6000004",
                partidas=[
                    _partida("001", product_id="P903", descripcion="a", spec={"z": 1}),
                    _partida("002", product_id="P903", descripcion="b", spec={"z": 1}),
                ],
            )
        ],
        product_specs={"P903": spec},
    )

    load_corpus(pg_session, corpus, seed=1)
    pg_session.flush()

    from database.models.intelligence import ProductDna
    from database.models.operational import Product

    for producto in pg_session.query(Product).filter_by(model="P903").all():
        dnas_vigentes = (
            pg_session.query(ProductDna).filter_by(product_id=producto.id, is_current=True).count()
        )
        assert dnas_vigentes == 1


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

    producto = pg_session.query(Product).filter_by(sku="DOC_C-001").one()
    assert producto.model == "P902"
    dna = pg_session.query(ProductDna).filter_by(product_id=producto.id).one()
    assert dna.summary == "TUBERIA DE PRUEBA DESCRIPCION COMERCIAL"
    assert "clasificacion" not in dna.summary.lower()
    assert "contrastar" not in dna.summary.lower()


def test_load_corpus_campo_tecnico_faltante_marca_descripcion_tecnica_aunque_el_spec_este_completo(
    pg_session: Session,
) -> None:
    """Regresión real (Persona 1, 22-sep-2026): 4 de las 6 partidas con la
    anomalía `CAMPO_TECNICO_FALTANTE` traen `technical_spec` COMPLETO,
    idéntico al de catálogo -- el corpus recorta la descripción comercial,
    no el spec estructurado. El diff de claves nunca detecta eso; la señal
    correcta es la propia anomalía (`field="descripcion_tecnica"`)."""
    spec = ParsedProductSpec(
        id="P904",
        name="Tubería de prueba",
        description="Descripción completa de catálogo",
        spec={"material": "acero", "diametro_mm": 900},
    )
    anomalia = ParsedAnomaly(
        code="CAMPO_TECNICO_FALTANTE",
        field="descripcion_tecnica",
        expected_value="caracteristicas suficientes para clasificar",
        observed_value="informacion tecnica insuficiente",
    )
    corpus = ParsedCorpus(
        pedimentos=[
            _pedimento(
                "DOC_E",
                "26 00 0000 6000005",
                partidas=[
                    _partida(
                        "001",
                        product_id="P904",
                        descripcion="TUBERIA GENERICA",
                        spec={"material": "acero", "diametro_mm": 900},  # completo, idéntico
                        anomalies=[anomalia],
                    )
                ],
            )
        ],
        product_specs={"P904": spec},
    )

    load_corpus(pg_session, corpus, seed=1)
    pg_session.flush()

    from database.models.intelligence import ProductDna
    from database.models.operational import Product

    producto = pg_session.query(Product).filter_by(sku="DOC_E-001").one()
    dna = pg_session.query(ProductDna).filter_by(product_id=producto.id).one()
    assert dna.missing_information == ["descripcion_tecnica"]


def test_fix_missing_information_corrige_sin_tocar_pedimentos_ni_ground_truth(
    pg_session: Session,
) -> None:
    """El fix quirúrgico corrige `ProductDna.missing_information` de una
    carga ya hecha con el bug real, sin borrar ni recargar nada más."""
    spec = ParsedProductSpec(
        id="P905",
        name="Tubería de prueba 2",
        description="Descripción completa",
        spec={"material": "acero", "diametro_mm": 500},
    )
    anomalia = ParsedAnomaly(
        code="CAMPO_TECNICO_FALTANTE",
        field="descripcion_tecnica",
        expected_value="caracteristicas suficientes para clasificar",
        observed_value="informacion tecnica insuficiente",
    )
    corpus = ParsedCorpus(
        pedimentos=[
            _pedimento(
                "DOC_F",
                "26 00 0000 6000006",
                partidas=[
                    _partida(
                        "001",
                        product_id="P905",
                        descripcion="TUBERIA GENERICA 2",
                        spec={"material": "acero", "diametro_mm": 500},
                        anomalies=[anomalia],
                    )
                ],
            )
        ],
        product_specs={"P905": spec},
    )

    load_corpus(pg_session, corpus, seed=1)
    pg_session.flush()

    from database.models.intelligence import GroundTruthRecord, ProductDna
    from database.models.operational import Pedimento, Product

    # Simula el estado roto: como si el cargador viejo hubiera corrido.
    producto = pg_session.query(Product).filter_by(sku="DOC_F-001").one()
    dna = pg_session.query(ProductDna).filter_by(product_id=producto.id).one()
    dna.missing_information = []
    pg_session.flush()

    n_pedimentos_antes = pg_session.query(Pedimento).count()
    n_ground_truth_antes = pg_session.query(GroundTruthRecord).count()

    n_corregidos = fix_missing_information(pg_session, corpus)
    pg_session.flush()

    assert n_corregidos == 1
    pg_session.refresh(dna)
    assert dna.missing_information == ["descripcion_tecnica"]
    assert pg_session.query(Pedimento).count() == n_pedimentos_antes
    assert pg_session.query(GroundTruthRecord).count() == n_ground_truth_antes

    # idempotente: correrlo de nuevo no reporta correcciones de más.
    assert fix_missing_information(pg_session, corpus) == 0
