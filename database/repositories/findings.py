"""Qué hallazgos son los de AHORA, y no los de todas las veces que se miró.

Un pedimento se audita varias veces —antes y después de una rectificación, o
simplemente porque se volvió a medir— y cada auditoría deja los suyos. Leerlos
todos no es un historial: es el estado actual mal contado. El
`26 47 9999 600001` llegó a listar 41 hallazgos donde su revisión vigente tiene
8 (Persona 1, 23-sep).

VIVE AQUÍ PORQUE LO USAN DOS MUNDOS QUE NO SE IMPORTAN

La pantalla de hallazgos lo necesita para no repetir lo mismo ocho veces, y la
métrica del §26 lo necesita para no medir ocho veces el mismo acierto. Tenerlo
en el router obligaba a la evaluación a importar de la API, que es justo la
dependencia que el §29 prohíbe. Una sola regla, un solo sitio.

Queda una tercera copia con la misma intención en el tablero (`_por_partida`
del #100), con otra forma: allí la subconsulta es un `DISTINCT ON` sobre todas
las revisiones porque agrupa dinero, no filtra filas. Unificarlas es deuda
anotada, no un cambio que se hace de paso mientras se mide.
"""

from __future__ import annotations

import sqlalchemy as sa

from database.models import RiskFinding, ShadowReview


def de_la_ultima_revision() -> sa.ColumnElement[bool]:
    """Sólo los hallazgos de la revisión vigente de cada pedimento.

    Los que tienen `shadow_review_id` nulo SÍ pasan: son anteriores a que se
    registraran las revisiones (§81), así que no se les puede atribuir una
    revisión superada. Esconderlos sería perder datos en silencio.
    """
    ultima = (
        sa.select(ShadowReview.id)
        .where(ShadowReview.pedimento_id == RiskFinding.pedimento_id)
        .order_by(ShadowReview.created_at.desc())
        .limit(1)
        .correlate(RiskFinding)
        .scalar_subquery()
    )
    return sa.or_(
        RiskFinding.shadow_review_id == ultima,
        RiskFinding.shadow_review_id.is_(None),
    )
