"""Lectura de hallazgos del Pedimento Espejo (§9.3 y §9.4).

LA DISTINCIÓN QUE ESTA PANTALLA NO PUEDE PERDER

«Sin hallazgos» y «no pude revisarlo» son cosas distintas. Un pedimento que
nadie verificó no está limpio: está sin verificar. Si la interfaz los mezcla,
alguien presentará ante la autoridad un pedimento sin revisar creyendo que
pasó el filtro.

`ShadowComparison` los separa a propósito —`divergences` frente a
`unverifiable`— y expone `is_complete`. Pero **eso vive en memoria y no se
persiste**: `intelligence.risk_findings` guarda los hallazgos y nada dice qué
partidas no se pudieron comprobar.

Por eso esta API NUNCA afirma que un pedimento esté limpio. Devuelve
`coverage_known: false` y la pantalla dice «sin hallazgos en lo revisado», que
es lo único cierto con los datos que hay. Ver ARCHITECTURE_DECISION_REQUIRED.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from database.models import Pedimento, RiskFinding
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

    Hoy siempre `false`: `ShadowComparison.unverifiable` no se persiste. Sin
    esto, «cero hallazgos» no autoriza a decir «limpio» — sólo «no encontré
    nada en lo que se haya revisado», que puede ser nada.
    """

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
    sentencia = sa.select(RiskFinding)
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

    filas = session.scalars(
        sa.select(RiskFinding).where(RiskFinding.pedimento_id == pedimento_id)
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
            # Mientras `unverifiable` no se persista, la cobertura es
            # desconocida. Decir lo contrario haría que un pedimento sin
            # revisar pareciera limpio.
            "coverage_known": False,
        }
    )
