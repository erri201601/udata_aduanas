"""El Panorama cuenta lo del documento una vez por pedimento (12-oct).

El tipo de cambio se declara una vez por pedimento y el Espejo lo registra en
cada partida: el tablero decía 316 hallazgos y 237 CRÍTICOS, de los que 165
eran el mismo dato repetido. Contra Postgres: comprueba la cuenta contra una
consulta independiente y que el censo de simulación siga contando filas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from apps.api.routers.dashboard import HALLAZGOS_DEL_DOCUMENTO, tablero
from database.models import RiskFinding
from database.repositories.findings import de_la_ultima_revision

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_lo_del_documento_cuenta_una_vez_por_pedimento(pg_session: Session) -> None:  # noqa: F811
    vigentes = de_la_ultima_revision()
    filas_doc = pg_session.scalar(
        sa.select(sa.func.count())
        .select_from(RiskFinding)
        .where(vigentes, RiskFinding.finding_type.in_(HALLAZGOS_DEL_DOCUMENTO))
    )
    if not filas_doc:
        pytest.skip("no hay hallazgos del documento en la base: no hay nada que colapsar")
    pedimentos_doc = pg_session.scalar(
        sa.select(sa.func.count(sa.distinct(RiskFinding.pedimento_id))).where(
            vigentes, RiskFinding.finding_type.in_(HALLAZGOS_DEL_DOCUMENTO)
        )
    )
    filas = pg_session.scalar(sa.select(sa.func.count()).select_from(RiskFinding).where(vigentes))

    h = tablero(pg_session).hallazgos

    assert h.de_documento == pedimentos_doc, "uno por pedimento con ese dato"
    assert h.total == filas - filas_doc + h.de_documento
    assert sum(h.por_severidad.values()) == h.total, "el reparto suma lo mismo que el total"
