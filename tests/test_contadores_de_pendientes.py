"""El tablero, las métricas y la bandeja dicen el mismo número (ADR 0008).

LO QUE ESTE FICHERO PROTEGE

Que «esperan a una persona» sea UNA cifra en todo el sistema. El 7-oct, con la
bandeja vacía —César había dictaminado los 57 casos—, el tablero decía 33 y la
pantalla de precisión decía 4 610:

- el tablero contaba la decisión vigente con la bandera, sin mirar el
  dictamen: un caso dictaminado y luego reclasificado seguía «esperando»;
- las métricas contaban todas las decisiones del motor con la bandera, también
  las históricas: cada reclasificación sumaba una.

Los dos usan ahora `database.repositories.preguntas.pendientes`.

Contra Postgres, en una transacción que se revierte. Se mide la DIFERENCIA que
introducen las filas del test, no el total, para no depender de lo que haya en
la base; y en el CI, con la base vacía, la diferencia sigue siendo de 1: no
pasa en vacío.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from apps.api.routers.dashboard import tablero
from apps.api.routers.metrics import precision
from database.repositories.preguntas import pendientes

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada
from tests.test_pendientes_integracion import _ficha, _motor, _veredicto

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _los_tres(session: Session) -> tuple[int, int, int]:
    return (
        len(session.scalars(pendientes()).all()),
        tablero(session).clasificaciones.requieren_revision,
        precision(session).pendientes_de_revision,
    )


def test_los_tres_contadores_dicen_lo_mismo(pg_session: Session) -> None:  # noqa: F811
    antes = _los_tres(pg_session)

    # A: un caso que de verdad espera a una persona, clasificado dos veces.
    # Reclasificar no es otro caso: cuenta UNO.
    a = _ficha(pg_session)
    _motor(pg_session, a, 1)
    _motor(pg_session, a, 4)

    # B: el caso de los 33. Dictaminado y después reclasificado: la vigente
    # conserva la bandera, pero la ficha ya tiene dictamen. Cuenta CERO.
    b = _ficha(pg_session)
    revisada = _motor(pg_session, b, 1)
    _veredicto(pg_session, revisada, 2)
    _motor(pg_session, b, 3)

    despues = _los_tres(pg_session)
    assert [d - a for a, d in zip(antes, despues, strict=True)] == [1, 1, 1], (antes, despues)
