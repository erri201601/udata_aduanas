"""Lectura de hallazgos del Pedimento Espejo (§9.3 y §9.4).

LA DISTINCIÓN QUE ESTA PANTALLA NO PUEDE PERDER

«Sin hallazgos» y «no pude revisarlo» son cosas distintas. Un pedimento que
nadie verificó no está limpio: está sin verificar. Si la interfaz los mezcla,
alguien presentará ante la autoridad un pedimento sin revisar creyendo que
pasó el filtro.

`ShadowComparison` los separa a propósito —`divergences` frente a
`unverifiable`— y expone `is_complete`. Desde que existe
`intelligence.shadow_reviews` eso se persiste, así que la API ya puede decir
si consta o no qué se revisó.

Una auditoría es un evento, no un estado: el mismo pedimento se audita varias
veces y aquí se lee **la revisión más reciente**. Si nunca se auditó, no hay
fila, y `coverage_known` sigue en `false` — que es la verdad, no un valor por
omisión.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from database.models import Pedimento, RiskFinding, ShadowReview
from database.repositories.findings import de_la_ultima_revision
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import Field
from schemas.intelligence import RiskFindingRead
from schemas.operational import PedimentoRead

from apps.api.db import SessionDep

router = APIRouter(prefix="/findings", tags=["findings"])

LIMITE_MAXIMO = 200

#: De más grave a menos. El orden es el criterio de revisión: quien audita
#: empieza por lo que puede detener la mercancía, no por lo que llegó antes.
ORDEN_SEVERIDAD = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")


class PedimentoFindings(PedimentoRead):
    """Un pedimento con sus hallazgos y, sobre todo, con qué NO se sabe."""

    findings: list[RiskFindingRead] = Field(default_factory=list)

    coverage_known: bool = False
    """¿Consta qué se pudo verificar y qué no?

    `false` significa que este pedimento nunca se auditó, no que la auditoría
    fuera incompleta. Sin esto, «cero hallazgos» no autoriza a decir «limpio»
    — sólo «no encontré nada en lo que se haya revisado», que puede ser nada.
    """

    is_complete: bool | None = None
    """¿Se auditó TODO? `None` si nunca se auditó.

    Tres estados, no dos: auditado completo, auditado con partidas sin
    comprobar, y nunca auditado. Colapsar el tercero en el segundo haría que
    un pedimento sin tocar pareciera revisado a medias.
    """

    unverifiable: list[str] = Field(default_factory=list)
    """Partidas que no se pudieron comprobar, con su razón."""

    reviewed_at: datetime | None = None
    """Cuándo se auditó por última vez. `None` si nunca."""

    worst_severity: str | None = None
    """La peor severidad presente, o `None` si no hay hallazgos."""


def _peor_severidad(hallazgos: list[RiskFindingRead]) -> str | None:
    for nivel in ORDEN_SEVERIDAD:
        if any(h.severity == nivel for h in hallazgos):
            return nivel
    return None


@router.get("", summary="Hallazgos, del más grave al menos")
def listar_hallazgos(
    session: SessionDep,
    pedimento_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RiskFindingRead]:
    """Ordenados por severidad en la base, no en el cliente.

    Paginar por fecha y reordenar después daría una primera página sin los
    hallazgos graves si quedaron fuera del corte.
    """
    orden = sa.case(
        {nivel: i for i, nivel in enumerate(ORDEN_SEVERIDAD)},
        value=RiskFinding.severity,
        else_=len(ORDEN_SEVERIDAD),
    )
    sentencia = sa.select(RiskFinding).where(de_la_ultima_revision())
    if pedimento_id is not None:
        sentencia = sentencia.where(RiskFinding.pedimento_id == pedimento_id)

    filas = session.scalars(
        sentencia.order_by(orden, RiskFinding.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return [RiskFindingRead.model_validate(f, from_attributes=True) for f in filas]


@router.get("/pedimentos", summary="Pedimentos revisables")
def listar_pedimentos(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = 50,
) -> list[PedimentoRead]:
    filas = session.scalars(
        sa.select(Pedimento).order_by(Pedimento.operation_date.desc()).limit(limit)
    ).all()
    return [PedimentoRead.model_validate(f, from_attributes=True) for f in filas]


@router.get("/pedimentos/{pedimento_id}", summary="Un pedimento con sus hallazgos")
def obtener_pedimento(pedimento_id: uuid.UUID, session: SessionDep) -> PedimentoFindings:
    pedimento = session.get(Pedimento, pedimento_id)
    if pedimento is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pedimento no encontrado")

    # La revisión más reciente. Una auditoría es un evento: el mismo pedimento
    # se audita antes y después de una rectificación, y la última es la que
    # describe el estado actual. Va ANTES de los hallazgos porque los acota.
    revision = session.scalars(
        sa.select(ShadowReview)
        .where(ShadowReview.pedimento_id == pedimento_id)
        .order_by(ShadowReview.created_at.desc())
    ).first()

    filas = session.scalars(
        sa.select(RiskFinding)
        .where(RiskFinding.pedimento_id == pedimento_id)
        .where(de_la_ultima_revision())
    ).all()
    hallazgos = [RiskFindingRead.model_validate(f, from_attributes=True) for f in filas]
    hallazgos.sort(
        key=lambda h: (
            ORDEN_SEVERIDAD.index(h.severity)
            if h.severity in ORDEN_SEVERIDAD
            else len(ORDEN_SEVERIDAD)
        )
    )

    detalle = PedimentoFindings.model_validate(pedimento, from_attributes=True)
    return detalle.model_copy(
        update={
            "findings": hallazgos,
            "worst_severity": _peor_severidad(hallazgos),
            # Sin fila, nunca se auditó. No es lo mismo que auditar y no
            # encontrar nada, y por eso no se colapsan en el mismo valor.
            "coverage_known": revision is not None,
            "is_complete": revision.is_complete if revision else None,
            "unverifiable": list(revision.unverifiable) if revision else [],
            "reviewed_at": revision.created_at if revision else None,
        }
    )
