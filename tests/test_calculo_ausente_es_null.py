"""Un hallazgo sin cálculo guarda `NULL`, no el JSON `null` (13-oct).

La columna se creó sin `none_as_null` y 262 hallazgos sin monto aparecieron
como «con cálculo» en una consulta `IS NOT NULL`. Contra Postgres: es el
comportamiento del tipo en la base lo que importa, no el del modelo en memoria.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from database.models import RiskFinding

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_sin_calculo_es_null_de_sql(pg_session: Session) -> None:  # noqa: F811
    fila = RiskFinding(
        finding_type="MISSING_NOM",
        severity="HIGH",
        data_origin="SYNTHETIC",
        impact_calculation=None,
    )
    pg_session.add(fila)
    pg_session.flush()

    es_null = pg_session.scalar(
        sa.select(RiskFinding.impact_calculation.is_(None)).where(RiskFinding.id == fila.id)
    )
    assert es_null is True
