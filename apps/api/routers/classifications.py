"""Lectura de decisiones de clasificación (§18 y §49).

Lo que hace defendible una clasificación no es el código que devuelve, sino
poder explicar cómo se llegó a él. Un agente aduanal firma con su nombre: si
el sistema le da una caja negra con un número, no puede usarlo.

Por eso el detalle no devuelve sólo la fracción: devuelve la ruta de reglas,
las alternativas consideradas con su motivo de rechazo, y las evidencias con
su TIPO. Esa última distinción no es cosmética — `LEGAL_SOURCE` es fundamento
jurídico y `MODEL_OUTPUT` no lo es, y presentarlos igual arruina la
credibilidad de todo lo demás.

Sólo lectura. Persistir decisiones es del orquestador.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from database.models import (
    ClassificationCandidate,
    ClassificationDecision,
    EvidenceRecord,
)
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from schemas.intelligence import (
    ClassificationCandidateRead,
    ClassificationDecisionRead,
    EvidenceRecordRead,
)

from apps.api.db import SessionDep

router = APIRouter(prefix="/classifications", tags=["classifications"])

LIMITE_MAXIMO = 200

#: Los únicos tipos de evidencia que sostienen una afirmación jurídica (§8.1).
#: `MODEL_OUTPUT` interpreta y `COMPARABLE` —CBP CROSS, EBTI— es apoyo
#: interpretativo de otra jurisdicción: ninguno de los dos fundamenta.
TIPOS_QUE_FUNDAMENTAN = frozenset({"LEGAL_SOURCE"})


class DictamenRead(BaseModel):
    """Lo que una persona decidió sobre una decisión del motor."""

    decision_id: uuid.UUID
    fraction_code: str | None = None
    """`None` cuando el revisor confirmó que tampoco él puede determinarla:
    coincidir en que no se puede es un resultado, no un hueco."""
    reasoning: str | None = None
    created_at: datetime


class ClassificationDetail(ClassificationDecisionRead):
    """Una decisión con todo lo necesario para defenderla.

    Va todo junto porque quien audita necesita verlo junto: separar los
    candidatos o la evidencia en otra petición convertiría "explicar una
    decisión" en tres viajes y una reconstrucción manual.
    """

    candidates: list[ClassificationCandidateRead] = Field(default_factory=list)
    evidences: list[EvidenceRecordRead] = Field(default_factory=list)

    dictamen: DictamenRead | None = None
    """El veredicto humano sobre ESTA decisión, si alguien ya se pronunció.

    Sin esto la pantalla enseñaba «Sin fracción — requiere que una persona lo
    revise» sobre un caso que una persona YA había revisado, y el trabajo del
    clasificador quedaba invisible justo donde más falta hace: al lado de lo
    que la máquina no pudo.

    Es `None` cuando nadie ha dictaminado, que no es lo mismo que un dictamen
    vacío.
    """

    trace_available: bool = False
    """¿Se conservó la traza paso a paso de esta decisión?

    `rgi_trace` es nullable a propósito: `NULL` significa «de esta decisión no
    conservamos la traza», que es distinto de «no hubo pasos». Las decisiones
    anteriores a la columna llegan así, y la pantalla lo dice en vez de
    aparentar una explicación que no tiene.

    La traza se CONGELA al persistir; no se reconstruye. Reejecutar el motor
    para explicarla daría un razonamiento distinto al que se firmó si la
    tarifa cambió, y una auditoría que muestra otra cosa que lo firmado es
    peor que no tener auditoría.
    """


@router.get("", summary="Lista las decisiones de clasificación")
def listar_decisiones(
    session: SessionDep,
    product_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ClassificationDecisionRead]:
    """Decisiones, de la más reciente a la más antigua."""
    sentencia = sa.select(ClassificationDecision)
    if product_id is not None:
        sentencia = sentencia.where(ClassificationDecision.product_id == product_id)

    filas = session.scalars(
        sentencia.order_by(ClassificationDecision.operation_date.desc()).limit(limit).offset(offset)
    ).all()
    return [ClassificationDecisionRead.model_validate(f, from_attributes=True) for f in filas]


@router.get("/{decision_id}", summary="Una decisión con su traza y evidencias")
def obtener_decision(decision_id: uuid.UUID, session: SessionDep) -> ClassificationDetail:
    decision = session.get(ClassificationDecision, decision_id)
    if decision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisión no encontrada")

    candidatos = session.scalars(
        sa.select(ClassificationCandidate)
        .where(ClassificationCandidate.classification_decision_id == decision_id)
        .order_by(ClassificationCandidate.rank)
    ).all()

    # La decisión apunta a una evidencia principal; el resto se localiza por el
    # vínculo blando que ya usa evidence_records (subject_kind + subject_id).
    evidencias = session.scalars(
        sa.select(EvidenceRecord).where(
            sa.or_(
                EvidenceRecord.id == decision.evidence_id,
                sa.and_(
                    EvidenceRecord.subject_kind == "classification_decision",
                    EvidenceRecord.subject_id == decision_id,
                ),
            )
        )
    ).all()

    # El veredicto apunta a la decisión revisada, no al revés: se busca por
    # `reviews_decision_id`, que es lo que garantiza que un dictamen diga
    # siempre QUÉ revisó (#79).
    veredicto = session.scalars(
        sa.select(ClassificationDecision)
        .where(ClassificationDecision.reviews_decision_id == decision_id)
        .order_by(ClassificationDecision.created_at.desc())
    ).first()

    detalle = ClassificationDetail.model_validate(decision, from_attributes=True)
    return detalle.model_copy(
        update={
            "dictamen": (
                DictamenRead(
                    decision_id=veredicto.id,
                    fraction_code=veredicto.fraction_code,
                    reasoning=veredicto.reasoning,
                    created_at=veredicto.created_at,
                )
                if veredicto is not None
                else None
            ),
            "candidates": [
                ClassificationCandidateRead.model_validate(c, from_attributes=True)
                for c in candidatos
            ],
            "evidences": [
                EvidenceRecordRead.model_validate(e, from_attributes=True) for e in evidencias
            ],
            # `None` es «no se conservó», no «no hubo pasos». La distinción
            # es la que permite que la pantalla diga la verdad.
            "trace_available": decision.rgi_trace is not None,
        }
    )
