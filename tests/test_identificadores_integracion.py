"""`cargar_reglas`: vigencia y `None` frente a «ninguna aplica» (ADR 0012).

Contra Postgres, en una transacción que se revierte. Desde #257 la base
compartida tiene las reglas reales del Apéndice 8 sin fecha de fin: rigen
también en 2099. Cada test empieza vaciando la tabla dentro de su transacción
(se revierte con ella), o «no hay reglas vigentes» nunca sería cierto.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models import PedimentoIdentifierRequirement
from database.repositories.identificadores import cargar_reglas

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

PROCEDENCIA = {
    "data_origin": "SYNTHETIC",
    "source_url": "https://ejemplo.invalido/prueba",
    "content_hash": "0" * 64,
    "retrieved_at": datetime.now(UTC),
}


@pytest.fixture(autouse=True)
def _sin_reglas_reales(pg_session: Session) -> None:  # noqa: F811
    pg_session.execute(sa.delete(PedimentoIdentifierRequirement))


def _regla(codigo: str, desde: date, hasta: date | None = None) -> PedimentoIdentifierRequirement:
    return PedimentoIdentifierRequirement(
        identifier_code=codigo,
        identifier_level="G",
        condition_kind="PEDIMENTO_KEY",
        condition_value=codigo,
        valid_from=desde,
        valid_to=hasta,
        **PROCEDENCIA,
    )


def test_sin_reglas_vigentes_es_none(pg_session: Session) -> None:  # noqa: F811
    pg_session.add(_regla("V1", date(2098, 1, 1), date(2098, 12, 31)))
    pg_session.flush()
    assert cargar_reglas(pg_session, on_date=date(2099, 6, 1)) is None


def test_lo_vigente_se_aplica(pg_session: Session) -> None:  # noqa: F811
    pg_session.add_all([_regla("V1", date(2099, 1, 1)), _regla("V4", date(2100, 1, 1))])
    pg_session.flush()
    reglas = cargar_reglas(pg_session, on_date=date(2099, 6, 1))
    assert reglas is not None
    assert reglas.para(pedimento_key="V1", fraction_code=None, nico_code=None).del_documento == (
        "V1",
    )
    assert (
        reglas.para(pedimento_key="V4", fraction_code=None, nico_code=None).del_documento == ()
    ), "la V4 aún no rige en esa fecha"
