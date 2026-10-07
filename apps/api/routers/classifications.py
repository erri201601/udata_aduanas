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
    ProductDna,
)
from database.repositories.preguntas import dictamen_de, vigente_de
from database.repositories.tariff import TariffCatalogRepository
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

    en_catalogo: bool | None = None
    """¿La fracción del veredicto existe en la TIGIE vigente ese día?

    `None` cuando el veredicto no trae fracción: coincidir en que no se puede
    determinar no tiene nada que comprobar contra el catálogo.

    Se comprueba al LEER, no sólo al escribir, porque el guardarraíl del
    endpoint de revisión no arregla las filas que entraron antes de existir.
    Hay una: `73239399` sobre un sartén de acero inoxidable, donde la única
    fracción de esa subpartida es `73239305`. La pantalla lo dice en vez de
    pintarla en verde como si la tarifa la respaldara.
    """


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


def _en_catalogo(session: SessionDep, veredicto: ClassificationDecision) -> bool | None:
    """¿La fracción del veredicto está en la TIGIE vigente ese día?

    `None` cuando no hay nada que comprobar —el veredicto no trae fracción— y
    también cuando NO SE PUEDE comprobar, porque no hay tarifa cargada para esa
    fecha. Los dos casos son «no consta», y son distintos de `False`, que es
    «comprobado y no está». Devolver `False` con el catálogo vacío acusaría al
    revisor de un error que sólo demuestra que nos falta el catálogo.
    """
    if not veredicto.fraction_code:
        return None
    catalogo = TariffCatalogRepository(session)
    if not catalogo.hay_fracciones(on_date=veredicto.operation_date):
        return None
    return catalogo.fraccion_existe(on_date=veredicto.operation_date, code=veredicto.fraction_code)


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
            "dictamen": _dictamen(session, veredicto),
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


def _dictamen(session: SessionDep, veredicto: ClassificationDecision | None) -> DictamenRead | None:
    if veredicto is None:
        return None
    return DictamenRead(
        decision_id=veredicto.id,
        fraction_code=veredicto.fraction_code,
        reasoning=veredicto.reasoning,
        created_at=veredicto.created_at,
        en_catalogo=_en_catalogo(session, veredicto),
    )


class CasoVigente(BaseModel):
    """Lo que necesita la pantalla justo antes de enviar un veredicto."""

    decision: ClassificationDetail
    """La decisión VIGENTE del caso, que puede no ser la que se estaba mirando.
    Trae la traza, de donde sale el aviso de fracción descartada."""

    dictamen_del_caso: DictamenRead | None = None
    """El último veredicto de la ficha, revise la decisión que revise.

    No es `decision.dictamen`: ése se busca por `reviews_decision_id` y es el
    de ESA fila. Tras reclasificar un caso ya dictaminado, la vigente no tiene
    veredicto propio y la pantalla diría «sin dictaminar» sobre un caso que una
    persona ya cerró — eran 33 el 7-oct.
    """


@router.get(
    "/{decision_id}/vigente",
    summary="La decisión vigente del caso de esa decisión, y su dictamen",
    responses={409: {"description": "La ficha de esa decisión ya no es la vigente"}},
)
def caso_vigente(decision_id: uuid.UUID, session: SessionDep) -> CasoVigente:
    """A qué decisión va un veredicto dado desde la pantalla que explica otra.

    EL VEREDICTO VA AL CASO DE HOY, NO A LA FILA QUE SE PINTÓ (ADR 0008)

    El 6-oct un clasificador dio un veredicto desde una pestaña abierta de
    antes, y quedó colgado de una decisión de la víspera. Antes de enviar, la
    pantalla pide esto y manda el veredicto a `decision.id`.

    Mismo caso, misma mercancía: si el motor volvió a clasificar la MISMA
    ficha, lo que la persona dice sobre la mercancía sigue valiendo. Si la
    ficha cambió de versión, es otro caso con otros hechos, y mandar ahí el
    veredicto firmaría algo que la persona no vio: 409.

    Una decisión sin ficha no tiene caso al que agruparla: es su propia
    vigente.
    """
    decision = session.get(ClassificationDecision, decision_id)
    if decision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisión no encontrada")

    if decision.product_dna_id is None:
        # Un veredicto sin ficha apunta a la decisión que revisó: ésa es el caso.
        if decision.data_origin == "HUMAN_VALIDATED" and decision.reviews_decision_id:
            decision = session.get(ClassificationDecision, decision.reviews_decision_id)
            if decision is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "decisión revisada no encontrada")
        veredicto = session.scalars(
            sa.select(ClassificationDecision)
            .where(ClassificationDecision.reviews_decision_id == decision.id)
            .order_by(ClassificationDecision.created_at.desc())
        ).first()
        return CasoVigente(
            decision=obtener_decision(decision.id, session),
            dictamen_del_caso=_dictamen(session, veredicto),
        )

    ficha = session.get(ProductDna, decision.product_dna_id)
    if ficha is None or not ficha.is_current:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "la ficha de esta decisión cambió: es otro caso. Vuelve a cargar la decisión vigente.",
        )
    vigente = vigente_de(session, ficha.id)
    if vigente is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "el caso no tiene decisión del motor")
    return CasoVigente(
        decision=obtener_decision(vigente.id, session),
        dictamen_del_caso=_dictamen(session, dictamen_de(session, ficha.id)),
    )
