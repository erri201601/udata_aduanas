"""El Espejo espera lo que dictaminó un clasificador cuando lo hay (7-oct).

LO QUE ESTE FICHERO PROTEGE

Que donde el motor se abstiene —cuatro de cada diez partidas del corpus— el
Espejo compare la fracción declarada contra el dictamen de la ficha, si existe.
En el pedimento 600015 una olla de presión de aluminio se declaraba como
fregadero (73241001) y pasaba sin señalar, con el dictamen de César
—76151002— en la base.

Y que el dictamen sólo se use cuando dice qué es la mercancía: no un
FALTA_INFORMACION, y no una fracción que la TIGIE no tenga el día de la
operación.

Contra Postgres, en una transacción que se revierte. Necesita la tarifa
cargada: en el CI, con la base vacía, se salta y lo dice.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from apps.api.routers.pedimentos import _dictamen_de_la_ficha
from database.repositories.tariff import TariffCatalogRepository

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada
from tests.test_pendientes_integracion import _ficha, _motor, _veredicto

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

OPERACION = date(2026, 3, 15)


def _catalogo(session: Session) -> TariffCatalogRepository:
    catalogo = TariffCatalogRepository(session)
    if not catalogo.fraccion_existe(on_date=OPERACION, code="73121005"):
        pytest.skip("sin la tarifa cargada no hay fracción contra la que comprobar el dictamen")
    return catalogo


def test_usa_la_fraccion_del_dictamen_y_dice_de_quien_es(pg_session: Session) -> None:  # noqa: F811
    catalogo = _catalogo(pg_session)
    ficha = _ficha(pg_session)
    _veredicto(pg_session, _motor(pg_session, ficha, 1), 2)

    dictamen = _dictamen_de_la_ficha(pg_session, ficha.product_id, OPERACION, catalogo)

    assert dictamen is not None
    fraccion, _nico, fuente = dictamen
    assert fraccion == "73121005"
    assert fuente.startswith("dictamen de ")


def test_un_falta_informacion_no_dice_que_es_la_mercancia(pg_session: Session) -> None:  # noqa: F811
    catalogo = _catalogo(pg_session)
    ficha = _ficha(pg_session)
    _veredicto(pg_session, _motor(pg_session, ficha, 1), 2)
    _veredicto(pg_session, _motor(pg_session, ficha, 3), 4, falta_informacion=True)

    assert _dictamen_de_la_ficha(pg_session, ficha.product_id, OPERACION, catalogo) is None


def test_una_fraccion_que_la_tigie_no_tiene_ese_dia_no_se_usa(pg_session: Session) -> None:  # noqa: F811
    """Un dictamen no convierte en fracción un código que la tarifa no tiene."""
    catalogo = _catalogo(pg_session)
    ficha = _ficha(pg_session)
    _veredicto(pg_session, _motor(pg_session, ficha, 1), 2)

    antes_de_la_tigie = date(1990, 1, 1)
    assert _dictamen_de_la_ficha(pg_session, ficha.product_id, antes_de_la_tigie, catalogo) is None


def test_sin_dictamen_no_hay_nada_que_usar(pg_session: Session) -> None:  # noqa: F811
    catalogo = _catalogo(pg_session)
    ficha = _ficha(pg_session)
    _motor(pg_session, ficha, 1)

    assert _dictamen_de_la_ficha(pg_session, ficha.product_id, OPERACION, catalogo) is None
