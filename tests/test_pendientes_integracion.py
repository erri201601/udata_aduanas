"""Qué casos esperan a una persona, contra Postgres de verdad (ADR 0008).

`integration`: lo que se prueba es lo que hace la consulta —`DISTINCT ON`,
`NOT EXISTS`, `UNION ALL`— y eso sólo lo sabe la base. En una máquina sin
Postgres se saltan; en el CI corren.

`created_at` se pone a mano en cada fila: su valor por omisión es `now()`, que
dentro de una transacción es el MISMO instante para todas, y entonces «la
última» la elegiría la base al azar.

Cada test corre en una transacción que se revierte: no deja filas. Se mira sólo
si las decisiones del propio test están o no, para no depender de lo que haya
en la base.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from database.models import ClassificationDecision, Product, ProductDna
from database.repositories.preguntas import pendientes

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def _ficha(session: Session, *, version: int = 1, product: Product | None = None) -> ProductDna:
    if product is None:
        product = Product(
            sku=f"T-{uuid.uuid4().hex[:10]}", commercial_name="cable", data_origin="SYNTHETIC"
        )
        session.add(product)
        session.flush()
    dna = ProductDna(product_id=product.id, version=version, data_origin="SYNTHETIC")
    session.add(dna)
    session.flush()
    return dna


def _motor(
    session: Session, dna: ProductDna | None, minuto: int, *, pendiente: bool = True
) -> ClassificationDecision:
    d = ClassificationDecision(
        product_id=dna.product_id if dna else None,
        product_dna_id=dna.id if dna else None,
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="HUMAN_REVIEW_REQUIRED" if pendiente else "RESOLVED",
        fraction_code=None if pendiente else "73121005",
        engine_version="0.1.0",
        requires_human_review=pendiente,
        data_origin="SYNTHETIC",
        created_at=T0 + timedelta(minutes=minuto),
    )
    session.add(d)
    session.flush()
    return d


def _veredicto(
    session: Session,
    revisa: ClassificationDecision,
    minuto: int,
    *,
    falta_informacion: bool = False,
) -> ClassificationDecision:
    v = ClassificationDecision(
        product_id=revisa.product_id,
        product_dna_id=revisa.product_dna_id,
        reviews_decision_id=revisa.id,
        trade_flow="IMPORT",
        operation_date=revisa.operation_date,
        status="INSUFFICIENT_INFORMATION" if falta_informacion else "RESOLVED",
        fraction_code=None if falta_informacion else "73121005",
        engine_version="0.1.0",
        requires_human_review=False,
        data_origin="HUMAN_VALIDATED",
        created_at=T0 + timedelta(minutes=minuto),
    )
    session.add(v)
    session.flush()
    return v


def _pendientes(session: Session) -> set[uuid.UUID]:
    return {d.id for d in session.scalars(pendientes()).all()}


# ── Los dos huecos que dejaban trabajo hecho en la bandeja ──────────────────


def test_un_veredicto_sobre_una_decision_vieja_de_la_ficha_cierra_el_caso(
    pg_session: Session,  # noqa: F811
) -> None:
    """El caso de PED_SIM_004-011: veredicto desde una pestaña vieja.

    D1, luego el recálculo D2, y la persona dictamina D1. Ningún veredicto
    apunta a D2, pero el caso —la ficha— está dictaminado.
    """
    dna = _ficha(pg_session)
    d1 = _motor(pg_session, dna, 0)
    d2 = _motor(pg_session, dna, 10)
    _veredicto(pg_session, d1, 20)

    assert not _pendientes(pg_session) & {d1.id, d2.id}


def test_un_recalculo_posterior_al_veredicto_no_devuelve_el_caso(
    pg_session: Session,  # noqa: F811
) -> None:
    """Los 33 casos de César: dictaminados y después reclasificado el corpus.

    La decisión nueva queda como la vigente y no tiene veredicto que apunte a
    ella. Con la definición por decisión, volvía a la bandeja.
    """
    dna = _ficha(pg_session)
    d1 = _motor(pg_session, dna, 0)
    _veredicto(pg_session, d1, 10)
    d2 = _motor(pg_session, dna, 20)

    assert not _pendientes(pg_session) & {d1.id, d2.id}


# ── Los bordes ──────────────────────────────────────────────────────────────


def test_falta_informacion_tambien_cierra_el_caso(pg_session: Session) -> None:  # noqa: F811
    """Pide un dato, no otra opinión."""
    dna = _ficha(pg_session)
    d1 = _motor(pg_session, dna, 0)
    _veredicto(pg_session, d1, 10, falta_informacion=True)
    d2 = _motor(pg_session, dna, 20)

    assert d2.id not in _pendientes(pg_session)


def test_sin_veredicto_esta_pendiente_solo_la_vigente(pg_session: Session) -> None:  # noqa: F811
    dna = _ficha(pg_session)
    d1 = _motor(pg_session, dna, 0)
    d2 = _motor(pg_session, dna, 10)

    assert _pendientes(pg_session) & {d1.id, d2.id} == {d2.id}


def test_si_la_vigente_resolvio_el_caso_no_espera(pg_session: Session) -> None:  # noqa: F811
    """Una decisión vieja pendiente no cuenta: el estado es el último evento."""
    dna = _ficha(pg_session)
    d1 = _motor(pg_session, dna, 0)
    d2 = _motor(pg_session, dna, 10, pendiente=False)

    assert not _pendientes(pg_session) & {d1.id, d2.id}


def test_otra_version_de_la_ficha_es_otro_caso_y_vuelve(pg_session: Session) -> None:  # noqa: F811
    """El dictamen se pronunció sobre unos hechos que ya no son los que hay."""
    v1 = _ficha(pg_session)
    d1 = _motor(pg_session, v1, 0)
    _veredicto(pg_session, d1, 10)
    product = pg_session.get(Product, v1.product_id)
    v2 = _ficha(pg_session, version=2, product=product)
    d2 = _motor(pg_session, v2, 20)

    assert d2.id in _pendientes(pg_session)


def test_las_decisiones_sin_ficha_pasan_una_a_una(pg_session: Session) -> None:  # noqa: F811
    a = _motor(pg_session, None, 0)
    b = _motor(pg_session, None, 10)

    assert _pendientes(pg_session) >= {a.id, b.id}


# ── El script de la terminal ────────────────────────────────────────────────


def test_el_script_saca_el_sku_de_cada_producto(pg_session: Session) -> None:  # noqa: F811
    """`dict(resultado.tuples())` fallaba: un `Result` tiene `.keys()` y `dict()`
    lo trataba como mapping. Sólo se ve ejecutándolo contra filas de verdad."""
    from apps.evaluacion.preguntas_pendientes import skus_de

    dna = _ficha(pg_session)
    producto = pg_session.get(Product, dna.product_id)
    assert producto is not None

    assert skus_de(pg_session, {dna.product_id}) == {dna.product_id: producto.sku}
    assert skus_de(pg_session, set()) == {}


def test_el_script_corre_de_principio_a_fin(
    pg_session: Session,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Con su propia conexión, como en la terminal. `pg_session` sólo está
    para que la configuración apunte a la base de los tests de integración."""
    from apps.evaluacion.preguntas_pendientes import main

    assert main([]) == 0
    assert "casos pendientes" in capsys.readouterr().out
