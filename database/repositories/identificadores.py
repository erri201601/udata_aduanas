"""Qué identificadores exige una operación — lectura de
`regulatory.pedimento_identifier_requirements` (ADR 0012).

Mismo criterio que `compensatory_duties.py` y `programas.py`: el Espejo no
busca reglas, compara contra lo que recibe. Quien las busca es este módulo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from database.models.regulatory import PedimentoIdentifierRequirement as Regla

if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Exigidos:
    """Lo que exige una partida, separado por dónde se declara."""

    del_documento: tuple[str, ...]
    """Nivel `G`: se declaran en el pedimento."""
    de_la_partida: tuple[str, ...]
    """Nivel `P`: se declaran en la partida."""


@dataclass(frozen=True)
class ReglasDeIdentificadores:
    """Las reglas vigentes en la fecha de una operación. Se cargan una vez por
    pedimento: son pocas (el reconocimiento contó como mucho 12 claves)."""

    reglas: tuple[tuple[str, str, str, str], ...]
    """(identifier_code, identifier_level, condition_kind, condition_value)."""

    def para(
        self,
        *,
        pedimento_key: str | None,
        fraction_code: str | None,
        nico_code: str | None,
    ) -> Exigidos:
        """Los identificadores que exige lo DECLARADO.

        Se comprueba la coherencia del documento: si declara la clave V1 o la
        fracción 9803.00.01, tiene que declarar el identificador que eso
        exige. Si la fracción declarada está mal, eso ya lo dice
        `FRACTION_MISMATCH`; aquí no se mezcla.
        """
        hechos = {
            "PEDIMENTO_KEY": pedimento_key,
            "FRACTION": fraction_code,
            "NICO": f"{fraction_code}{nico_code}" if fraction_code and nico_code else None,
        }
        aplican = [
            (codigo, nivel)
            for codigo, nivel, tipo, valor in self.reglas
            if hechos.get(tipo) is not None and hechos[tipo] == valor
        ]
        return Exigidos(
            del_documento=tuple(dict.fromkeys(c for c, n in aplican if n == "G")),
            de_la_partida=tuple(dict.fromkeys(c for c, n in aplican if n == "P")),
        )


def cargar_reglas(session: Session, *, on_date: date) -> ReglasDeIdentificadores | None:
    """Las reglas vigentes en `on_date`, o `None` si no hay ninguna cargada.

    `None` se distingue de «hay reglas y ninguna aplica»: con lo primero el
    Espejo dice que no sabe qué identificadores exige la operación; con lo
    segundo, que no exige ninguno de los estructurables.
    """
    filas = session.execute(
        sa.select(
            Regla.identifier_code,
            Regla.identifier_level,
            Regla.condition_kind,
            Regla.condition_value,
        )
        .where(
            Regla.valid_from <= on_date,
            sa.or_(Regla.valid_to.is_(None), Regla.valid_to >= on_date),
        )
        .order_by(Regla.identifier_code)
    ).all()
    if not filas:
        return None
    return ReglasDeIdentificadores(reglas=tuple((f[0], f[1], f[2], f[3]) for f in filas))
