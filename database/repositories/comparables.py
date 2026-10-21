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
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

#: Cuánto texto se muestra del criterio. Lo demás está en la URL pública.
LARGO_EXTRACTO: Final = 420

#: Desde aquí se toma una ventana, no «hasta el punto»: «Model no.» o «Inc.»
#: no terminan la frase y la cortaban a la mitad.
_SUBPARTIDA = re.compile(r"The applicable (?:sub)?heading for ", re.I)
_HOLDING = re.compile(r"HOLDINGS?:\s*(.{40,}?)(?:\n\s*\n|$)", re.S)
_HECHOS = re.compile(r"FACTS:\s*(.{40,}?)(?:\n\s*\n|$)", re.S)
#: Las BTI (ADR 0020) traen la justificación bajo una etiqueta nuestra, en el
#: idioma del país emisor.
_JUSTIFICACION = re.compile(r"JUSTIFICACIÓN DE LA CLASIFICACIÓN:\s*(.+?)(?:\n\s*\n|$)", re.S)


def _plano(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _recorte(texto: str) -> str:
    plano = _plano(texto)
    if len(plano) <= LARGO_EXTRACTO:
        return plano
    return plano[:LARGO_EXTRACTO].rsplit(" ", 1)[0] + " …"


def criterio_de(texto: str) -> tuple[str, str]:
    """`(extracto, de_dónde)`: la justificación de una BTI, la frase con la que
    CBP fija la subpartida, la sección HOLDING o, si no hay ninguna, el inicio
    de los hechos."""
    m = _JUSTIFICACION.search(texto)
    if m:
        return _recorte(m.group(1)), "justificacion"
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


def texto_para_vector(asunto: str, texto: str) -> str:
    """Lo que se vectoriza de una resolución: qué mercancía era y cómo se
    clasificó. Sin membretes ni cortesías, que sólo meten ruido."""
    extracto, _ = criterio_de(texto)
    return f"{_plano(asunto)}\n{extracto}"


def comparables_de(
    session: Session,
    hs6: str,
    *,
    limite: int = 8,
    vector: Sequence[float] | None = None,
) -> tuple[int, list[tuple[ComparableRuling, float | None]]]:
    """Las resoluciones que citan la subpartida, con su parecido a `vector`.

    Primero las vigentes. Dentro de ellas, con `vector`, por parecido (coseno),
    y las que no tienen vector al final. Sin `vector`, por fecha, de la más
    reciente a la más antigua. Devuelve también el total.
    """
    donde = ComparableRuling.hs6_codes.contains([hs6])
    total = session.scalar(sa.select(sa.func.count()).select_from(ComparableRuling).where(donde))
    if vector is None:
        filas = session.scalars(
            sa.select(ComparableRuling)
            .where(donde)
            .order_by(ComparableRuling.is_revoked, ComparableRuling.ruling_date.desc())
            .limit(limite)
        ).all()
        return total or 0, [(f, None) for f in filas]
    distancia = ComparableRuling.embedding.cosine_distance(list(vector))
    pares = session.execute(
        sa.select(ComparableRuling, distancia.label("distancia"))
        .where(donde)
        .order_by(
            ComparableRuling.is_revoked,
            distancia.asc().nulls_last(),
            ComparableRuling.ruling_date.desc(),
        )
        .limit(limite)
    ).tuples()
    return total or 0, [(f, None if d is None else round(1 - float(d), 3)) for f, d in pares]
