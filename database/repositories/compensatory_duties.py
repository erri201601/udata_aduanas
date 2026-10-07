"""Cuota compensatoria vigente para un origen/fracción — lectura de
`regulatory.compensatory_duties` (ADR 0009).

Separado de `core/shadow/compare.py`, mismo criterio que
`database/repositories/exchange.py`: el comparador no busca la tasa, sólo
la compara contra lo declarado. Quien la busca es este módulo.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import sqlalchemy as sa

from database.models.regulatory import CompensatoryDuty

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.orm import Session


def normalizar_nombre(nombre: str) -> str:
    """Mayúsculas, sin puntuación, espacios colapsados.

    Para la coincidencia EXACTA (nunca aproximada) entre `exporter_name` y
    `operational.suppliers.legal_name` — decisión de Persona 1, 6-oct: una
    coincidencia parecida le daría a alguien la tasa de un exportador
    nombrado por error, que sería inventar una exención. "Oriental
    Technical Supply Co. Ltd." y "ORIENTAL TECHNICAL SUPPLY CO LTD" deben
    normalizar igual; "Oriental Technical Supply Co." (sin "Ltd.") NO debe
    coincidir con ninguna — es un nombre distinto, no una variante de
    formato.
    """
    sin_puntuacion = re.sub(r"[.,;:()]", "", nombre.upper())
    return " ".join(sin_puntuacion.split())


def cuotas_vigentes(
    session: Session, *, on_date: date, origin_country: str, fraction_code: str
) -> list[CompensatoryDuty]:
    """Las filas vigentes para este origen/fracción, en `on_date`.

    Puede haber más de una: un exportador nombrado con su propia tasa, y la
    residual (`exporter_name IS NULL`, "las demás") — quien llama decide
    cuál aplica cruzando contra el proveedor real de la partida. Ninguna
    fila devuelta significa "no se sabe", no "no aplica" (ver el docstring
    de `ExpectedItem.compensatory_duty_applies`).
    """
    return list(
        session.scalars(
            sa.select(CompensatoryDuty)
            .where(
                CompensatoryDuty.origin_country == origin_country,
                CompensatoryDuty.fraction_code == fraction_code,
                CompensatoryDuty.valid_from <= on_date,
                sa.or_(CompensatoryDuty.valid_to.is_(None), CompensatoryDuty.valid_to >= on_date),
            )
            .order_by(CompensatoryDuty.exporter_name.is_(None))
        ).all()
    )
