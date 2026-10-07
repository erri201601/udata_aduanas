"""`GET /classifications/{id}/vigente`: a qué decisión va un veredicto (ADR 0008).

LO QUE ESTE FICHERO PROTEGE

Que un veredicto dado desde la pantalla que EXPLICA una decisión vaya al caso
de hoy y no a la fila que se pintó. El 6-oct un clasificador dictaminó desde
una pestaña abierta de la víspera y su veredicto quedó colgado de una decisión
que el motor ya no sostenía.

Y que el dictamen que se enseña sea el del CASO: tras reclasificar un caso ya
dictaminado, la vigente no tiene veredicto propio. Buscarlo por
`reviews_decision_id` diría «sin dictaminar» sobre 33 casos que una persona
había cerrado (7-oct).

Contra Postgres, en una transacción que se revierte.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from apps.api.routers.classifications import caso_vigente
from fastapi import HTTPException

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada
from tests.test_pendientes_integracion import _ficha, _motor, _veredicto

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_desde_una_decision_vieja_se_llega_a_la_vigente_con_el_dictamen_del_caso(
    pg_session: Session,  # noqa: F811
) -> None:
    """El caso de los 33: dictaminado, y después reclasificado."""
    ficha = _ficha(pg_session)
    vieja = _motor(pg_session, ficha, 1)
    veredicto = _veredicto(pg_session, vieja, 2)
    hoy = _motor(pg_session, ficha, 3)

    caso = caso_vigente(vieja.id, pg_session)

    assert caso.decision.id == hoy.id, "el veredicto iría a una decisión que ya no rige"
    assert caso.dictamen_del_caso is not None, "diría «sin dictaminar» sobre un caso cerrado"
    assert caso.dictamen_del_caso.decision_id == veredicto.id
    assert caso.decision.dictamen is None, "el de la FILA sigue siendo el de la fila"


def test_desde_un_veredicto_se_llega_al_mismo_caso(pg_session: Session) -> None:  # noqa: F811
    ficha = _ficha(pg_session)
    revisada = _motor(pg_session, ficha, 1)
    veredicto = _veredicto(pg_session, revisada, 2)

    assert caso_vigente(veredicto.id, pg_session).decision.id == revisada.id


def test_manda_el_ultimo_veredicto_del_caso(pg_session: Session) -> None:  # noqa: F811
    """La regla del #213: un FALTA_INFORMACION posterior sustituye al dictamen."""
    ficha = _ficha(pg_session)
    primera = _motor(pg_session, ficha, 1)
    _veredicto(pg_session, primera, 2)
    segunda = _motor(pg_session, ficha, 3)
    ultimo = _veredicto(pg_session, segunda, 4, falta_informacion=True)

    caso = caso_vigente(primera.id, pg_session)

    assert caso.dictamen_del_caso is not None
    assert caso.dictamen_del_caso.decision_id == ultimo.id
    assert caso.dictamen_del_caso.fraction_code is None


def test_si_la_ficha_cambio_es_otro_caso(pg_session: Session) -> None:  # noqa: F811
    """Mandar el veredicto a la ficha nueva firmaría hechos que nadie vio."""
    vieja = _ficha(pg_session)
    decision = _motor(pg_session, vieja, 1)
    vieja.is_current = False
    pg_session.flush()

    with pytest.raises(HTTPException) as e:
        caso_vigente(decision.id, pg_session)
    assert e.value.status_code == 409


def test_una_decision_sin_ficha_es_su_propia_vigente(pg_session: Session) -> None:  # noqa: F811
    suelta = _motor(pg_session, None, 1)
    veredicto = _veredicto(pg_session, suelta, 2)

    caso = caso_vigente(suelta.id, pg_session)

    assert caso.decision.id == suelta.id
    assert caso.dictamen_del_caso is not None
    assert caso.dictamen_del_caso.decision_id == veredicto.id


def test_una_decision_que_no_existe_da_404(pg_session: Session) -> None:  # noqa: F811
    with pytest.raises(HTTPException) as e:
        caso_vigente(uuid.uuid4(), pg_session)
    assert e.value.status_code == 404
