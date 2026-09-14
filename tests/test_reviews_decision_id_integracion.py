"""Las constraints de `reviews_decision_id`, contra Postgres de verdad.

`integration`: necesitan la base, porque lo que prueban es precisamente lo que
hace la base cuando la aplicación se salta sus propias comprobaciones. En una
máquina sin Postgres se saltan; en el dev server corren.

Cada test abre y cierra su propia transacción (`pg_session` la revierte): no
dejan filas.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from database.models import ClassificationDecision
from sqlalchemy.exc import IntegrityError

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _decision(**kw: object) -> ClassificationDecision:
    campos: dict[str, object] = {
        "trade_flow": "IMPORT",
        "operation_date": date(2024, 3, 15),
        "status": "HUMAN_REVIEW_REQUIRED",
        "data_origin": "SYNTHETIC",
        "requires_human_review": True,
    }
    campos.update(kw)
    return ClassificationDecision(**campos)


def _maquina(session: Session) -> ClassificationDecision:
    d = _decision()
    session.add(d)
    session.flush()
    return d


def test_dos_veredictos_sobre_la_misma_decision_los_rechaza_la_base(
    pg_session: Session,  # noqa: F811
) -> None:
    """EL UNIQUE: si alguien se salta la aplicación, decide Postgres."""
    original = _maquina(pg_session)
    for _ in range(2):
        pg_session.add(
            _decision(
                data_origin="HUMAN_VALIDATED",
                status="RESOLVED",
                requires_human_review=False,
                reviews_decision_id=original.id,
            )
        )

    with pytest.raises(IntegrityError) as exc:
        pg_session.flush()
    assert "uq_classification_decisions_reviews_decision_id" in str(exc.value)


def test_un_veredicto_que_no_dice_que_revisa_lo_rechaza_la_base(
    pg_session: Session,  # noqa: F811
) -> None:
    pg_session.add(_decision(data_origin="HUMAN_VALIDATED", reviews_decision_id=None))

    with pytest.raises(IntegrityError) as exc:
        pg_session.flush()
    assert "revision_dice_que_revisa" in str(exc.value)


def test_una_decision_de_maquina_no_puede_apuntar_a_otra(
    pg_session: Session,  # noqa: F811
) -> None:
    original = _maquina(pg_session)
    pg_session.add(_decision(data_origin="SYNTHETIC", reviews_decision_id=original.id))

    with pytest.raises(IntegrityError) as exc:
        pg_session.flush()
    assert "revision_dice_que_revisa" in str(exc.value)


def test_una_decision_revisada_no_se_puede_borrar(
    pg_session: Session,  # noqa: F811
) -> None:
    """RESTRICT: con la decisión se iría la mitad de la medición."""
    original = _maquina(pg_session)
    pg_session.add(
        _decision(
            data_origin="HUMAN_VALIDATED",
            status="RESOLVED",
            requires_human_review=False,
            reviews_decision_id=original.id,
        )
    )
    pg_session.flush()
    pg_session.delete(original)

    with pytest.raises(IntegrityError):
        pg_session.flush()
