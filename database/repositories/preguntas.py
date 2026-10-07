"""Qué casos esperan a una persona. Una sola definición (ADR 0008).

HABÍA TRES, Y NINGUNA ERA LA BUENA

Hasta el 6-oct, la bandeja (`GET /review`), el script de preguntas y el
recálculo al contestar usaban cada uno su conjunto de pendientes:

    · la bandeja: la última decisión de cada `product_dna_id`, contando
      también las filas HUMAN_VALIDATED en ese «la última»;
    · el script: `status = 'HUMAN_REVIEW_REQUIRED'`, la última por producto;
    · el recálculo: TODAS las pendientes, no sólo la última.

Y medido contra la base compartida, la bandeja enseñaba 90 casos de los que
**33 ya tenían veredicto de César**: el corpus se reclasificó después de sus
veredictos y la decisión nueva quedó como «la más reciente», sin veredicto que
apuntara a ella. Un tercio de la bandeja era trabajo ya hecho.

LA UNIDAD ES EL CASO, NO LA DECISIÓN

Es lo que se decidió el 5-oct para el tablero (`_ya_dictaminada` en
`dashboard.py`) y lo que el #213 puso en las mediciones. Un caso es una ficha:

    vigente(ficha)   la última decisión no HUMAN_VALIDATED de ese product_dna_id
    dictamen(ficha)  el último HUMAN_VALIDATED de ese product_dna_id, revise la
                     decisión que revise
    pendiente        vigente.requires_human_review Y la ficha sin dictamen

Un FALTA_INFORMACION también saca el caso: pide un dato, no otra opinión. Si
la ficha cambia de versión es otro `product_dna_id`, otro caso, y vuelve.

Las decisiones sin `product_dna_id` pasan una a una: no hay caso al que
agruparlas, y descartarlas sería perder casos en silencio.

LA FORMA DE LA CONSULTA ESTÁ MEDIDA

`DISTINCT ON` en vez de un `max(created_at)` correlacionado: con el NOT EXISTS
del dictamen, la correlacionada pasaba de 16 ms a 379 ms con 6 175 filas; ésta
da los mismos 57 casos en 11 ms y sin índice nuevo (Persona 1, EXPLAIN contra
la base compartida, 6-oct).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from database.models import ClassificationDecision

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

_HUMANO = "HUMAN_VALIDATED"


def vigentes() -> sa.CTE:
    """La decisión vigente de cada ficha: la última del motor, no de una persona."""
    d = ClassificationDecision
    return (
        sa.select(d.id, d.product_dna_id, d.requires_human_review)
        .where(d.data_origin != _HUMANO, d.product_dna_id.is_not(None))
        .distinct(d.product_dna_id)
        .order_by(d.product_dna_id, d.created_at.desc())
        .cte("vigente")
    )


def fichas_dictaminadas() -> sa.CTE:
    """Las fichas con algún veredicto humano, sea cual sea la decisión revisada."""
    d = ClassificationDecision
    return (
        sa.select(d.product_dna_id)
        .where(d.data_origin == _HUMANO, d.product_dna_id.is_not(None))
        .distinct()
        .cte("dictaminada")
    )


def pendientes() -> sa.Select[Any]:
    """Las decisiones que esperan a una persona: una por caso, sin página.

    Sin `LIMIT` a propósito: una página es cosa de quien la pinta, no de la
    definición. Contar sobre una página haría decir 14 donde son 20.
    """
    d = ClassificationDecision
    vigente = vigentes()
    dictaminada = fichas_dictaminadas()

    con_ficha = sa.select(vigente.c.id).where(
        vigente.c.requires_human_review.is_(True),
        ~sa.exists().where(dictaminada.c.product_dna_id == vigente.c.product_dna_id),
    )
    # Con alias propio: es la misma tabla que la consulta exterior, y sin él
    # SQLAlchemy podría correlacionarla en vez de leerla entera.
    suelta = aliased(d, name="sin_ficha")
    sin_ficha = sa.select(suelta.id).where(
        suelta.product_dna_id.is_(None),
        suelta.requires_human_review.is_(True),
        suelta.data_origin != _HUMANO,
    )
    return sa.select(d).where(d.id.in_(sa.union_all(con_ficha, sin_ficha)))


def preguntas_de(decision: ClassificationDecision) -> list[dict[str, Any]]:
    """Las preguntas del último paso de la traza, tal cual las dejó el motor.

    El último paso es donde el motor se atascó: los anteriores continuaron, y
    preguntar por una regla que ya pasó no desatasca nada. No se filtra nada
    aquí: decidir qué se pregunta —y qué ya está contestado— es del motor.
    """
    traza = decision.rgi_trace or []
    if not traza or not isinstance(traza[-1], dict):
        return []
    return [
        q
        for q in traza[-1].get("preguntas") or []
        if isinstance(q, dict) and q.get("codigo") and q.get("exige")
    ]


def productos_que_preguntaban(session: Session, clausula: str) -> list[uuid.UUID]:
    """Los productos cuyo caso pendiente tiene esa cláusula delante.

    Va por la cláusula y no por la posición: la respuesta se guarda por
    (término de la ficha, cláusula) y el motor la aplica a cualquier posición
    cuyo texto diga esa frase.

    El conjunto sale de la TRAZA y no de buscar qué fichas dicen el término:
    eso exigiría repetir aquí la regla de emparejamiento del motor, y esa copia
    ya se desvió una vez.
    """
    afectados: list[uuid.UUID] = []
    vistos: set[uuid.UUID] = set()
    for decision in session.scalars(pendientes()).all():
        if decision.product_id is None or decision.product_id in vistos:
            continue
        if any(q["exige"] == clausula for q in preguntas_de(decision)):
            vistos.add(decision.product_id)
            afectados.append(decision.product_id)
    return afectados
