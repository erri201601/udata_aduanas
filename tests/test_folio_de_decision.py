"""El folio de §17: `AD-AAAA-NNNNNN`, asignado por la base (ADR 0015).

Contra Postgres, en una transacción que se revierte: la secuencia avanza (las
secuencias no se revierten) y eso está bien, un folio saltado no es un folio
repetido. Lo que se comprueba es lo que no puede fallar: formato, unicidad y
orden, y que se encuentre por folio.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from database.models import ClassificationDecision

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

FOLIO = re.compile(r"^AD-(\d{4})-(\d{6,})$")


def _decision() -> ClassificationDecision:
    return ClassificationDecision(
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="HUMAN_REVIEW_REQUIRED",
        engine_version="0.1.0",
        requires_human_review=True,
        data_origin="SYNTHETIC",
    )


def test_la_base_asigna_un_folio_por_decision_y_en_orden(pg_session: Session) -> None:  # noqa: F811
    a, b = _decision(), _decision()
    pg_session.add(a)
    pg_session.flush()
    pg_session.add(b)
    pg_session.flush()

    ma, mb = FOLIO.match(a.folio), FOLIO.match(b.folio)
    assert ma and mb, (a.folio, b.folio)
    assert ma.group(1) == str(datetime.now(ZoneInfo("America/Mexico_City")).year), (
        "el año es el de emisión en la Ciudad de México"
    )
    assert int(mb.group(2)) > int(ma.group(2))


def test_dos_decisiones_nunca_comparten_folio(pg_session: Session) -> None:  # noqa: F811
    repetidos = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT folio FROM intelligence.classification_decisions "
            "GROUP BY folio HAVING count(*) > 1) r"
        )
    )
    assert repetidos == 0


def test_toda_decision_existente_tiene_un_folio_bien_formado(pg_session: Session) -> None:  # noqa: F811
    malos = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM intelligence.classification_decisions "
            "WHERE folio !~ '^AD-[0-9]{4}-[0-9]{6,}$'"
        )
    )
    assert malos == 0


def test_se_encuentra_por_su_folio(pg_session: Session) -> None:  # noqa: F811
    from apps.api.routers.classifications import listar_decisiones

    d = _decision()
    pg_session.add(d)
    pg_session.flush()

    encontradas = listar_decisiones(pg_session, folio=f" {d.folio.lower()} ")
    assert [e.id for e in encontradas] == [d.id], (
        "se cita como se dicta: sin espacios ni mayúsculas"
    )
