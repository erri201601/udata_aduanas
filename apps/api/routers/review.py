"""Bandeja de revisión humana (§39).

Las correcciones humanas son el activo más valioso del sistema: son lo único
que ninguna otra parte genera, y lo que permite medir «fraction accuracy» y
«human review rate» del §39.

LA CORRECCIÓN NO SOBRESCRIBE A LA MÁQUINA

Medir la precisión exige conservar las dos respuestas: la del motor y la de
la persona. Si la revisión editara la decisión original, el numerador de esa
métrica desaparecería — y con él la única forma de saber si el sistema está
mejorando.

Por eso una revisión crea una fila NUEVA con `data_origin = HUMAN_VALIDATED`,
y la original sólo deja de estar pendiente. Ambas comparten `product_dna_id`,
que es lo que permite emparejarlas al evaluar.

Es el mismo criterio que Persona 1 aplicó a `shadow_reviews`: una revisión es
un evento, no un atributo.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

import sqlalchemy as sa
from database.models import ClassificationDecision, Product
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from schemas.intelligence import ClassificationDecisionRead

from apps.api.db import SessionDep

router = APIRouter(prefix="/review", tags=["review"])

LIMITE_MAXIMO = 200

#: Lo que puede decir quien revisa.
Veredicto = Literal["CONFIRMA", "CORRIGE"]


class PendienteRead(ClassificationDecisionRead):
    """Una decisión esperando a una persona, con contexto para decidir."""

    producto: str | None = None
    """Nombre comercial, para no tener que abrir otra pantalla."""
    sku: str | None = None
    pasos_traza: int = 0
    """Cuántas reglas se evaluaron. Cero significa que no consta el
    razonamiento, y eso cambia cuánto puede fiarse quien revisa."""


class RevisionRequest(BaseModel):
    """El veredicto de una persona."""

    veredicto: Veredicto
    reviewer: str = Field(min_length=1, max_length=64)
    """Quién revisa. Una corrección anónima no es auditable."""
    fraction_code: str | None = Field(default=None, max_length=8)
    """La fracción correcta. Obligatoria si se corrige."""
    nota: str | None = None
    """Por qué. Es lo que hace utilizable la corrección para entrenar."""


class RevisionResponse(BaseModel):
    original_id: uuid.UUID
    revision_id: uuid.UUID
    """La fila nueva con el veredicto humano. La original se conserva."""
    veredicto: Veredicto
    fraction_code: str | None = None


@router.get("", summary="Decisiones esperando revisión humana")
def pendientes(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = 50,
) -> list[PendienteRead]:
    """La bandeja, de la más antigua a la más reciente.

    Lo más viejo primero a propósito: en una bandeja de trabajo, lo que lleva
    más tiempo esperando es lo que más urge, no lo que acaba de llegar.
    """
    filas = session.scalars(
        sa.select(ClassificationDecision)
        .where(
            ClassificationDecision.requires_human_review.is_(True),
            # Las revisiones humanas no vuelven a la bandeja.
            ClassificationDecision.data_origin != "HUMAN_VALIDATED",
        )
        .order_by(ClassificationDecision.created_at)
        .limit(limit)
    ).all()

    pendientes: list[PendienteRead] = []
    for fila in filas:
        producto = session.get(Product, fila.product_id) if fila.product_id else None
        detalle = PendienteRead.model_validate(fila, from_attributes=True)
        pendientes.append(
            detalle.model_copy(
                update={
                    "producto": producto.commercial_name if producto else None,
                    "sku": producto.sku if producto else None,
                    "pasos_traza": len(fila.rgi_trace or []),
                }
            )
        )
    return pendientes


@router.post(
    "/{decision_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Confirma o corrige una decisión",
)
def revisar(
    decision_id: uuid.UUID, peticion: RevisionRequest, session: SessionDep
) -> RevisionResponse:
    """Registra el veredicto humano SIN borrar el de la máquina.

    Crea una decisión nueva marcada `HUMAN_VALIDATED` y saca la original de la
    bandeja. Las dos comparten `product_dna_id`, que es lo que permite
    emparejarlas para medir precisión (§39).
    """
    original = session.get(ClassificationDecision, decision_id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisión no encontrada")

    if original.data_origin == "HUMAN_VALIDATED":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "esta fila ya es una revisión humana: no se revisa una revisión",
        )

    if peticion.veredicto == "CORRIGE" and not peticion.fraction_code:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "corregir exige la fracción correcta: sin ella la corrección no dice nada",
        )

    codigo = peticion.fraction_code if peticion.veredicto == "CORRIGE" else original.fraction_code

    revision = ClassificationDecision(
        product_id=original.product_id,
        product_dna_id=original.product_dna_id,
        trade_flow=original.trade_flow,
        operation_date=original.operation_date,
        status="RESOLVED" if codigo else "HUMAN_REVIEW_REQUIRED",
        chapter=codigo[:2] if codigo else None,
        heading=codigo[:4] if codigo else None,
        subheading=codigo[:6] if codigo else None,
        fraction_code=codigo,
        reasoning=_razonamiento(peticion, original),
        rgi_path=list(original.rgi_path or []),
        # La traza es del motor. Copiarla aquí haría parecer que la persona
        # siguió esas reglas, y no las siguió: revisó su conclusión.
        rgi_trace=None,
        engine_version=original.engine_version,
        # HUMAN_VALIDATED es lo que distingue esta fila de la del motor y lo
        # que permite emparejarlas al evaluar (§39).
        data_origin="HUMAN_VALIDATED",
        # Ya la revisó una persona: no vuelve a la bandeja.
        requires_human_review=False,
        confidence=None,
    )
    session.add(revision)

    # La original se conserva intacta salvo por salir de la bandeja: es la
    # respuesta de la máquina y es la mitad de la métrica.
    original.requires_human_review = False
    session.commit()

    return RevisionResponse(
        original_id=original.id,
        revision_id=revision.id,
        veredicto=peticion.veredicto,
        fraction_code=codigo,
    )


def _razonamiento(peticion: RevisionRequest, original: ClassificationDecision) -> str:
    """Deja por escrito quién revisó, qué dijo y sobre qué.

    Una corrección sin motivo no sirve para entrenar: se sabe que el sistema
    se equivocó, no en qué.
    """
    partes = [f"Revisión humana de {peticion.reviewer}: {peticion.veredicto.lower()}."]
    if peticion.veredicto == "CORRIGE":
        partes.append(
            f"El motor propuso {original.fraction_code or 'sin fracción'}; "
            f"se corrige a {peticion.fraction_code}."
        )
    if peticion.nota:
        partes.append(peticion.nota)
    return " ".join(partes)
