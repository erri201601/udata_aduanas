"""Calidad de datos (§38): lo que la base tiene que cumplir, no el código.

Los tests de integración comprueban que el código hace lo que dice sobre datos
que fabrican ellos mismos. Éstos miran los datos que YA están: vigencias que no
se solapan, procedencia completa, criterio humano que dice quién lo firmó,
simulaciones marcadas como tales. Cada uno nació de algo que pasó o casi pasó:

- dos versiones vigentes del FIX el mismo día (#250): `MultipleResultsFound`;
- una tasa PROSEC contradictoria cargada en silencio (#261);
- un `HUMAN_VALIDATED` que ningún humano dio sería la peor mentira posible.

Se ejecutan contra la base del `.env`. Con la base vacía de la CI se saltan con
motivo: no hay datos que comprobar, y pasar en vacío sería un verde falso.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = [pytest.mark.integration, pytest.mark.data_quality]

#: Tabla → columnas de su clave natural (sin la vigencia).
CLAVES: dict[str, tuple[str, ...]] = {
    "regulatory.tariff_fractions": ("code",),
    "regulatory.nicos": ("full_code",),
    "regulatory.tariff_headings": ("code",),
    "regulatory.exchange_rates": ("currency",),
    "regulatory.fraction_nom_requirements": ("fraction_code", "nom_code", "numeral"),
    "regulatory.compensatory_duties": ("origin_country", "fraction_code", "exporter_name"),
    "regulatory.prosec_rates": ("sector_code", "fraction_code", "scope_note"),
    "regulatory.regla_8a_fractions": ("sector_code", "fraction_code"),
    "regulatory.pedimento_identifier_requirements": (
        "identifier_code",
        "condition_kind",
        "condition_value",
    ),
}

ORIGENES = ("OFFICIAL", "PUBLIC", "LICENSED", "SYNTHETIC", "HUMAN_VALIDATED")

#: Las reglas de las RGCE demasiado largas para el modelo de embeddings: se
#: partieron por fracción (`ingestion.dof.cli --split-long-rules`), y el
#: fragmento entero se queda sin vector a propósito.
SIN_VECTOR_A_PROPOSITO = frozenset({"1.1.6", "4.5.31", "7.3.3"})


def _hay_filas(session: Session, tabla: str) -> bool:
    return bool(session.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {tabla})")))


def _solapes(session: Session, tabla: str) -> list[sa.Row[tuple[object, object]]]:
    iguales = " AND ".join(f"a.{c} IS NOT DISTINCT FROM b.{c}" for c in CLAVES[tabla])
    return list(
        session.execute(
            sa.text(
                f"SELECT a.id, b.id FROM {tabla} a JOIN {tabla} b "
                f"ON {iguales} AND a.id < b.id "
                "AND a.valid_from <= COALESCE(b.valid_to, 'infinity'::date) "
                "AND b.valid_from <= COALESCE(a.valid_to, 'infinity'::date) LIMIT 5"
            )
        ).all()
    )


def test_el_detector_de_solapes_si_encuentra_uno(pg_session: Session) -> None:  # noqa: F811
    """Control negativo: un test de calidad que nunca falla no demuestra nada."""
    from datetime import UTC, date, datetime
    from decimal import Decimal

    from database.models import ExchangeRate

    comun = {
        "currency": "ZZZ",
        "data_origin": "SYNTHETIC",
        "source_url": "https://ejemplo.invalido",
        "content_hash": "0" * 64,
        "retrieved_at": datetime.now(UTC),
    }
    pg_session.add_all(
        [
            ExchangeRate(rate=Decimal("1"), valid_from=date(2099, 1, 1), valid_to=None, **comun),
            ExchangeRate(rate=Decimal("2"), valid_from=date(2099, 2, 1), valid_to=None, **comun),
        ]
    )
    pg_session.flush()
    assert _solapes(pg_session, "regulatory.exchange_rates")


@pytest.mark.parametrize("tabla", sorted(CLAVES))
def test_las_vigencias_no_se_solapan(pg_session: Session, tabla: str) -> None:  # noqa: F811
    """Dos versiones vigentes el mismo día hacen que una consulta por fecha
    devuelva dos respuestas (o reviente). Es lo que pasó con el FIX (#250)."""
    if not _hay_filas(pg_session, tabla):
        pytest.skip(f"{tabla} está vacía")
    solapes = _solapes(pg_session, tabla)
    assert solapes == [], f"{tabla}: versiones que se solapan, p. ej. {solapes[:3]}"


@pytest.mark.parametrize("tabla", sorted(CLAVES))
def test_toda_fila_normativa_dice_de_donde_sale(pg_session: Session, tabla: str) -> None:  # noqa: F811
    """§13: URL, hash, origen válido y una vigencia que no acaba antes de empezar."""
    if not _hay_filas(pg_session, tabla):
        pytest.skip(f"{tabla} está vacía")
    malas = pg_session.scalar(
        sa.text(
            f"SELECT count(*) FROM {tabla} WHERE "
            "coalesce(source_url, '') = '' OR coalesce(content_hash, '') = '' "
            "OR data_origin NOT IN :origenes OR (valid_to IS NOT NULL AND valid_to < valid_from)"
        ).bindparams(sa.bindparam("origenes", expanding=True)),
        {"origenes": list(ORIGENES)},
    )
    assert malas == 0, f"{tabla}: {malas} filas sin procedencia completa o con vigencia imposible"


def test_todo_criterio_humano_dice_quien_lo_firmo(pg_session: Session) -> None:  # noqa: F811
    """Un `HUMAN_VALIDATED` que ningún humano dio es la peor mentira posible:
    hace pasar una conjetura nuestra por criterio de un clasificador."""
    if not _hay_filas(pg_session, "intelligence.classification_decisions"):
        pytest.skip("no hay decisiones")
    sin_firma = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM intelligence.classification_decisions "
            "WHERE data_origin = 'HUMAN_VALIDATED' AND ("
            "  reasoning IS NULL OR reasoning !~ '^Revisión humana de [^:]+:' "
            "  OR reviews_decision_id IS NULL)"
        )
    )
    assert sin_firma == 0, f"{sin_firma} veredictos humanos sin firmante o sin decisión revisada"
    sinonimos = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM regulatory.nomenclature_synonyms "
            "WHERE data_origin = 'HUMAN_VALIDATED' AND coalesce(answered_by, '') = ''"
        )
    )
    assert sinonimos == 0, f"{sinonimos} respuestas de vocabulario firmadas sin firmante"


def test_lo_sintetico_se_presenta_como_simulacion(pg_session: Session) -> None:  # noqa: F811
    """§33: un pedimento sintético, y todo lo que se deriva de él, es simulación."""
    if not _hay_filas(pg_session, "operational.pedimentos"):
        pytest.skip("no hay pedimentos")
    pedimentos = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM operational.pedimentos "
            "WHERE data_origin = 'SYNTHETIC' AND NOT is_simulation"
        )
    )
    hallazgos = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM intelligence.risk_findings r "
            "JOIN operational.pedimentos p ON p.id = r.pedimento_id "
            "WHERE p.is_simulation AND NOT r.is_simulation"
        )
    )
    oportunidades = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM intelligence.opportunity_findings o "
            "JOIN operational.pedimentos p ON p.id = o.pedimento_id "
            "WHERE p.is_simulation AND NOT o.is_simulation"
        )
    )
    assert (pedimentos, hallazgos, oportunidades) == (0, 0, 0)


def test_las_oportunidades_nunca_nacen_validadas(pg_session: Session) -> None:  # noqa: F811
    """§23: el motor sólo produce `POTENTIAL`; pasar a VALIDATED es de una persona."""
    if not _hay_filas(pg_session, "intelligence.opportunity_findings"):
        pytest.skip("no hay oportunidades")
    estados = set(
        pg_session.scalars(sa.text("SELECT DISTINCT status FROM intelligence.opportunity_findings"))
    )
    assert estados <= {"POTENTIAL", "VALIDATED", "REJECTED"}
    validadas_sin_persona = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM intelligence.opportunity_findings "
            "WHERE status <> 'POTENTIAL' AND data_origin <> 'HUMAN_VALIDATED'"
        )
    )
    assert validadas_sin_persona == 0


def test_todo_fragmento_que_cabe_tiene_vector(pg_session: Session) -> None:  # noqa: F811
    """Un fragmento sin vector no sale en la búsqueda por significado: existe y
    no se encuentra. Sólo se aceptan los demasiado largos, ya partidos."""
    if not _hay_filas(pg_session, "regulatory.legal_chunks"):
        pytest.skip("no hay fragmentos")
    if not pg_session.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM regulatory.legal_chunks WHERE embedding IS NOT NULL)")
    ):
        pytest.skip("la base no tiene vectores: el backfill no se ha corrido aquí")
    sin_vector = set(
        pg_session.scalars(
            sa.text("SELECT article FROM regulatory.legal_chunks WHERE embedding IS NULL")
        )
    )
    assert sin_vector <= SIN_VECTOR_A_PROPOSITO, (
        f"fragmentos sin vector: {sorted(sin_vector - SIN_VECTOR_A_PROPOSITO)[:10]} — "
        "corre `python -m rag.backfill_embeddings --target local`"
    )
