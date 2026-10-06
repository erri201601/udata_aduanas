"""Tipo de cambio vigente en una fecha — lectura de `regulatory.exchange_rates`.

Separado de `core/taxation/money.py` a propósito: `Money.convert()` exige
la tasa explícita y no la busca ni la supone (su propio docstring lo dice);
este módulo es justo "de dónde sale" esa tasa cuando quien llama sí la
necesita buscar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from database.models.regulatory import ExchangeRate

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.orm import Session


def tasa_vigente(session: Session, *, on_date: date, currency: str) -> Decimal | None:
    """Pesos mexicanos por 1 unidad de `currency`, vigente en `on_date`.

    `None` si ninguna fila cubre esa fecha — fuera del rango ya cargado, o
    una fecha futura todavía sin publicar. No se extrapola el último valor
    conocido más allá de su propio `valid_to`: eso sería afirmar un tipo de
    cambio que el DOF no publicó para ese día (§14 maestro).
    """
    fila = session.scalars(
        sa.select(ExchangeRate).where(
            ExchangeRate.currency == currency,
            ExchangeRate.valid_from <= on_date,
            sa.or_(ExchangeRate.valid_to.is_(None), ExchangeRate.valid_to >= on_date),
        )
    ).one_or_none()
    return fila.rate if fila is not None else None
