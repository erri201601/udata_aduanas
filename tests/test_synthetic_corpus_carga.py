"""Integración: `synthetic/` + `ingestion.sintetico.load` de punta a punta
contra Postgres real, dentro de una transacción que SIEMPRE se revierte --
nada de esto puede quedar persistido (ver `synthetic/README.md`, el plan de
carga real todavía no está aprobado por Persona 1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.operational import Pedimento, PedimentoItem, Product
from ingestion.sintetico.corpus_espejo import parse_corpus
from ingestion.sintetico.load import load_corpus
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from synthetic.corpus import construir_corpus_nuevo

if TYPE_CHECKING:
    from collections.abc import Iterator

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


def _tasa_fija(_fecha: date) -> Decimal:
    return Decimal("17.00")


def test_carga_de_punta_a_punta_sin_romper_nada(pg_session: Session) -> None:
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)

    reporte = load_corpus(pg_session, corpus, seed=20260921)

    # 5 del 13-oct + MISSING_NOM y MISSED_PROSEC del 20-oct.
    assert reporte.pedimentos_creados == 7
    assert reporte.pedimentos_saltados == 0
    assert reporte.partidas_creadas == 7

    pesos = pg_session.scalars(
        sa.select(PedimentoItem.net_weight_kg).where(PedimentoItem.net_weight_kg.is_not(None))
    ).all()
    # Las 6 de cable; la estufa (P013) no lleva peso.
    assert len(pesos) == 6
    assert all(p > 0 for p in pesos)

    rectificacion = pg_session.scalars(
        sa.select(Pedimento).where(Pedimento.pedimento_number == "26 47 9999 600020")
    ).one()
    original = pg_session.scalars(
        sa.select(Pedimento).where(Pedimento.pedimento_number == "26 47 9999 600016")
    ).one()
    assert rectificacion.rectifies_pedimento_id == original.id
    assert rectificacion.rectification_number == 1


def test_el_sku_compartido_no_choca_contra_la_unicidad_por_cliente(pg_session: Session) -> None:
    """Confirma en Postgres real, no sólo en el dataclass, que dos
    `Product` con el mismo `sku` y distinto `client_id` SÍ pueden coexistir
    -- la precondición real de `INCONSISTENT_SKU_CLASSIFICATION`."""
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)

    load_corpus(pg_session, corpus, seed=20260921)

    filas = pg_session.scalars(sa.select(Product).where(Product.sku == "SKU-CABLE-18MM-001")).all()
    assert len(filas) == 2
    assert filas[0].client_id != filas[1].client_id
    assert filas[0].id != filas[1].id


def test_es_idempotente_no_duplica_si_se_corre_dos_veces(pg_session: Session) -> None:
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)

    primera = load_corpus(pg_session, corpus, seed=20260921)
    segunda = load_corpus(pg_session, corpus, seed=20260921)

    assert primera.pedimentos_creados == 7
    assert segunda.pedimentos_creados == 0
    assert segunda.pedimentos_saltados == 7
