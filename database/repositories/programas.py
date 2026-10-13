"""Tasas de PROSEC y Regla 8ª vigentes en una fecha — lectura de
`regulatory.prosec_rates` y `regulatory.regla_8a_fractions` (ADR 0011).

Mismo criterio que `compensatory_duties.py`: el Opportunity Finder no busca
tasas, las recibe. Quien las busca es este módulo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from core.opportunity import OpcionDePrograma, OpportunityKind

from database.models.regulatory import ProsecRate, Regla8aFraction

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.orm import Session

    from database.repositories.tariff import TariffCatalogRepository


def _vigente(
    modelo: type[ProsecRate] | type[Regla8aFraction], on_date: date
) -> sa.ColumnElement[bool]:
    return sa.and_(
        modelo.valid_from <= on_date,
        sa.or_(modelo.valid_to.is_(None), modelo.valid_to >= on_date),
    )


@dataclass(frozen=True)
class CatalogoDeProgramas:
    """Lo vigente de los dos catálogos en la fecha de una operación.

    Se carga una vez por pedimento. La Regla 8ª no depende de la fracción de
    la mercancía —es una 9802 por sector— y se reparte igual a cada partida.
    """

    prosec: tuple[OpcionDePrograma, ...]
    regla_8a: tuple[OpcionDePrograma, ...]

    def para(self, fraction_code: str | None) -> tuple[OpcionDePrograma, ...]:
        """Las opciones de una partida. `()` sin fracción declarada."""
        if not fraction_code:
            return ()
        return (
            *(o for o in self.prosec if o.fraction_code == fraction_code),
            *self.regla_8a,
        )


def cargar_programas(
    session: Session, *, on_date: date, catalogo: TariffCatalogRepository
) -> CatalogoDeProgramas | None:
    """Los dos catálogos vigentes en `on_date`, o `None` si no hay ninguno cargado.

    `None` y un catálogo vacío no son lo mismo: con `None` el informe dice que
    PROSEC y Regla 8ª no se evaluaron; con un catálogo sin filas para la
    fracción, que se evaluaron y no hay.

    La tasa de la Regla 8ª se lee de la fracción 9802 en la LIGIE, no de esta
    tabla. Una 9802 sin tasa vigente se omite: no se supone cero.
    """
    prosec = tuple(
        OpcionDePrograma(
            kind=OpportunityKind.PROSEC,
            sector_code=fila.sector_code,
            sector_name=fila.sector_name,
            fraction_code=fila.fraction_code,
            igi_rate=fila.igi_rate,
            is_partial=fila.is_partial,
            scope_note=fila.scope_note,
            source_ids=(fila.source_id,) if fila.source_id else (),
            data_origin=fila.data_origin,
        )
        for fila in session.scalars(
            sa.select(ProsecRate)
            .where(_vigente(ProsecRate, on_date))
            .order_by(ProsecRate.fraction_code, ProsecRate.sector_code)
        )
    )

    regla_8a: list[OpcionDePrograma] = []
    filas_8a = session.scalars(
        sa.select(Regla8aFraction)
        .where(_vigente(Regla8aFraction, on_date))
        .order_by(Regla8aFraction.sector_code)
    ).all()
    for fila in filas_8a:
        tasa = catalogo.igi_rate(on_date=on_date, fraction_code=fila.fraction_code)
        if tasa is None:
            continue
        regla_8a.append(
            OpcionDePrograma(
                kind=OpportunityKind.REGLA_8A,
                sector_code=fila.sector_code,
                sector_name=fila.sector_name,
                fraction_code=fila.fraction_code,
                igi_rate=tasa,
                scope_note=fila.scope_note,
                source_ids=(fila.source_id,) if fila.source_id else (),
                data_origin=fila.data_origin,
            )
        )

    if not prosec and not filas_8a:
        return None
    return CatalogoDeProgramas(prosec=prosec, regla_8a=tuple(regla_8a))
