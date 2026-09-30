"""Tests de integración de `ingestion.snice.load.add_missing_heading_groups`
(ADR 0004) contra el Postgres local.

Usa códigos de partida/subpartida que NO existen en la LIGIE real ("9999"/
"999911"/"999912") para no chocar con las 6 855 filas ya cargadas por
`load_tariff_headings` -- mismo criterio que ya usó esta sesión para
identificadores de pedimento y reglas RGCE de prueba.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models.regulatory import TariffHeading, TariffHeadingGroup
from ingestion.snice.load import LIGIE_VALID_FROM, add_missing_heading_groups
from ingestion.snice.tariff_headings import ParsedHeadingGroup
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

HASH = "c" * 64
PARTIDA = "9999"
SUB_1 = "999911"
SUB_2 = "999912"


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


def _sembrar_partida_y_subpartidas(session: Session) -> None:
    """Simula que `load_tariff_headings` ya corrió: una partida (9999) y dos
    subpartidas (999911, 999912) ya en `tariff_headings`, sin grupo todavía."""
    ahora = datetime.now(UTC)
    session.add(
        TariffHeading(
            code=PARTIDA,
            level=4,
            chapter="99",
            description="Partida de prueba, no existe en la LIGIE real.",
            data_origin="OFFICIAL",
            valid_from=LIGIE_VALID_FROM,
            source_url="https://ejemplo.invalido/prueba",
            content_hash=HASH,
            retrieved_at=ahora,
        )
    )
    for sub in (SUB_1, SUB_2):
        session.add(
            TariffHeading(
                code=sub,
                level=6,
                chapter="99",
                description=f"Subpartida de prueba {sub}.",
                data_origin="OFFICIAL",
                valid_from=LIGIE_VALID_FROM,
                source_url="https://ejemplo.invalido/prueba",
                content_hash=HASH,
                retrieved_at=ahora,
            )
        )
    session.flush()


def _grupos_de_la_partida_de_prueba(session: Session) -> list[TariffHeadingGroup]:
    """Acotado a la partida falsa ("9999") -- la base local ya tiene 1 024
    grupos reales cargados (ADR 0004), y `.query(TariffHeadingGroup).all()`
    a secas los recogería también."""
    partida = session.query(TariffHeading).filter_by(code=PARTIDA, level=4).one()
    return (
        session.query(TariffHeadingGroup)
        .filter_by(parent_heading_id=partida.id)
        .order_by(TariffHeadingGroup.ordinal)
        .all()
    )


def test_crea_el_grupo_y_asocia_sus_subpartidas(pg_session: Session) -> None:
    _sembrar_partida_y_subpartidas(pg_session)
    grupo = ParsedHeadingGroup(parent_code=PARTIDA, ordinal=1, description="Grupo de prueba:")

    reporte = add_missing_heading_groups(
        pg_session,
        groups=[grupo],
        subheading_to_group={SUB_1: (PARTIDA, 1), SUB_2: (PARTIDA, 1)},
        ligie_content_hash=HASH,
    )

    assert reporte.grupos_creados == 1
    assert reporte.subpartidas_asociadas == 2
    assert reporte.necesitan_validacion == ()

    (fila_grupo,) = _grupos_de_la_partida_de_prueba(pg_session)
    assert fila_grupo.description == "Grupo de prueba:"
    assert fila_grupo.data_origin == "OFFICIAL"
    assert fila_grupo.content_hash == HASH

    sub1 = pg_session.query(TariffHeading).filter_by(code=SUB_1).one()
    sub2 = pg_session.query(TariffHeading).filter_by(code=SUB_2).one()
    assert sub1.group_id == fila_grupo.id
    assert sub2.group_id == fila_grupo.id


def test_es_idempotente(pg_session: Session) -> None:
    _sembrar_partida_y_subpartidas(pg_session)
    grupo = ParsedHeadingGroup(parent_code=PARTIDA, ordinal=1, description="Grupo de prueba:")
    asociacion = {SUB_1: (PARTIDA, 1)}

    primera = add_missing_heading_groups(
        pg_session, groups=[grupo], subheading_to_group=asociacion, ligie_content_hash=HASH
    )
    segunda = add_missing_heading_groups(
        pg_session, groups=[grupo], subheading_to_group=asociacion, ligie_content_hash=HASH
    )

    assert primera.grupos_creados == 1
    assert segunda.grupos_creados == 0
    assert primera.subpartidas_asociadas == 1
    assert segunda.subpartidas_asociadas == 0
    assert segunda.necesitan_validacion == ()
    assert len(_grupos_de_la_partida_de_prueba(pg_session)) == 1


def test_reordenamiento_sin_leer_queda_en_needs_validation(pg_session: Session) -> None:
    """Mismo texto (mismo `description_hash`) bajo la misma partida, pero
    con `ordinal` distinto al ya guardado -- decisión de Persona 1 (ADR
    0004): no se renombra sola, se reporta y no se toca."""
    _sembrar_partida_y_subpartidas(pg_session)
    grupo_original = ParsedHeadingGroup(
        parent_code=PARTIDA, ordinal=1, description="Grupo de prueba:"
    )
    add_missing_heading_groups(
        pg_session, groups=[grupo_original], subheading_to_group={}, ligie_content_hash=HASH
    )

    grupo_reordenado = ParsedHeadingGroup(
        parent_code=PARTIDA, ordinal=2, description="Grupo de prueba:"
    )
    reporte = add_missing_heading_groups(
        pg_session,
        groups=[grupo_reordenado],
        subheading_to_group={SUB_1: (PARTIDA, 2)},
        ligie_content_hash=HASH,
    )

    assert reporte.grupos_creados == 0
    assert len(reporte.necesitan_validacion) == 1
    assert "reordenamiento" in reporte.necesitan_validacion[0]

    (fila_grupo,) = _grupos_de_la_partida_de_prueba(pg_session)
    assert fila_grupo.ordinal == 1, "no se toca la fila existente"

    sub1 = pg_session.query(TariffHeading).filter_by(code=SUB_1).one()
    assert sub1.group_id is None, "no se asocia bajo un ordinal que no coincide"


def test_grupo_sin_partida_cargada_queda_en_needs_validation(pg_session: Session) -> None:
    """La partida del grupo no está en `tariff_headings` -- no se inventa a
    qué partida pertenece, se reporta."""
    grupo = ParsedHeadingGroup(parent_code="00000", ordinal=1, description="Huérfano:")

    reporte = add_missing_heading_groups(
        pg_session, groups=[grupo], subheading_to_group={}, ligie_content_hash=HASH
    )

    assert reporte.grupos_creados == 0
    assert len(reporte.necesitan_validacion) == 1
    assert "no está en tariff_headings" in reporte.necesitan_validacion[0]
    assert pg_session.query(TariffHeadingGroup).filter_by(description="Huérfano:").count() == 0


def test_dos_grupos_distintos_bajo_la_misma_partida_no_chocan(pg_session: Session) -> None:
    """`(parent_heading_id, description_hash, valid_from)` es la llave --
    dos grupos de texto distinto bajo la misma partida conviven."""
    _sembrar_partida_y_subpartidas(pg_session)
    grupo_1 = ParsedHeadingGroup(parent_code=PARTIDA, ordinal=1, description="Primer grupo:")
    grupo_2 = ParsedHeadingGroup(parent_code=PARTIDA, ordinal=2, description="Segundo grupo:")

    reporte = add_missing_heading_groups(
        pg_session,
        groups=[grupo_1, grupo_2],
        subheading_to_group={SUB_1: (PARTIDA, 1), SUB_2: (PARTIDA, 2)},
        ligie_content_hash=HASH,
    )

    assert reporte.grupos_creados == 2
    assert reporte.subpartidas_asociadas == 2
    filas = {g.ordinal: g.description for g in _grupos_de_la_partida_de_prueba(pg_session)}
    assert filas == {1: "Primer grupo:", 2: "Segundo grupo:"}
