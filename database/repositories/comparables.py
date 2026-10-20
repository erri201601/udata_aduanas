"""Casos comparables de otras aduanas para una subpartida (ADR 0019).

Se buscan por HS6, el único nivel común a México y a la autoridad que
resolvió. El extracto es texto literal de la resolución, nunca un resumen
generado: un LLM resumiendo una resolución extranjera podría hacerla sonar a
criterio aplicable aquí.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from database.models import ComparableRuling

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: Cuánto texto se muestra del criterio. Lo demás está en la URL pública.
LARGO_EXTRACTO: Final = 420

#: Desde aquí se toma una ventana, no «hasta el punto»: «Model no.» o «Inc.»
#: no terminan la frase y la cortaban a la mitad.
_SUBPARTIDA = re.compile(r"The applicable (?:sub)?heading for ", re.I)
_HOLDING = re.compile(r"HOLDINGS?:\s*(.{40,}?)(?:\n\s*\n|$)", re.S)
_HECHOS = re.compile(r"FACTS:\s*(.{40,}?)(?:\n\s*\n|$)", re.S)


def _plano(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _recorte(texto: str) -> str:
    plano = _plano(texto)
    if len(plano) <= LARGO_EXTRACTO:
        return plano
    return plano[:LARGO_EXTRACTO].rsplit(" ", 1)[0] + " …"


def criterio_de(texto: str) -> tuple[str, str]:
    """`(extracto, de_dónde)`: la frase con la que CBP fija la subpartida, la
    sección HOLDING o, si no hay ninguna, el inicio de los hechos."""
    m = _SUBPARTIDA.search(texto)
    if m:
        return _recorte(texto[m.start() : m.start() + LARGO_EXTRACTO * 2]), "subpartida"
    m = _HOLDING.search(texto)
    if m:
        return _recorte(m.group(1)), "holding"
    m = _HECHOS.search(texto)
    if m:
        return _recorte(m.group(1)), "hechos"
    return _recorte(texto), "inicio"


def comparables_de(
    session: Session, hs6: str, *, limite: int = 8
) -> tuple[int, list[ComparableRuling]]:
    """Las resoluciones que citan la subpartida: primero las vigentes y las
    más recientes. Devuelve también el total, para decir cuántas hay de más."""
    donde = ComparableRuling.hs6_codes.contains([hs6])
    total = session.scalar(sa.select(sa.func.count()).select_from(ComparableRuling).where(donde))
    filas = session.scalars(
        sa.select(ComparableRuling)
        .where(donde)
        .order_by(ComparableRuling.is_revoked, ComparableRuling.ruling_date.desc())
        .limit(limite)
    ).all()
    return total or 0, list(filas)
