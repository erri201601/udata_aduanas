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

LA BANDEJA DICE POR QUÉ ESTÁ CADA CASO

No todos los pendientes piden lo mismo, y hasta ahora se veían iguales. Desde
que la RGI 3 c) marca sus resoluciones (PR #69 de Persona 1) conviven tres
especies:

    · no se pudo resolver — falta información
    · se resolvió y aun así hay que mirarlo
    · se llegó al desempate de último recurso, que aplica la regla
      correctamente y no distingue nada: entre una computadora y un monitor
      elige el monitor porque 8528 va después de 8471

Un revisor que no distingue la tercera de la primera no sabe qué le están
pidiendo: en una falta información, en la otra sobra una respuesta que nadie
debería firmar tal cual.

`causas` es una LISTA, no un valor único, y no lleva severidad. Elegir una
sola exigiría un orden de precedencia que el dato no sostiene —un caso puede
carecer de información Y haber llegado al desempate— y ordenarlas por gravedad
sería una opinión disfrazada de dato. Se nombran; el revisor decide.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final, Literal

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

#: La regla de desempate de último recurso: «la última por orden de
#: numeración». Aplica correctamente y no distingue nada.
REGLA_DESEMPATE = "RGI-3c"

#: Por qué un caso está en la bandeja. Sin severidad y sin precedencia: son
#: causas concurrentes, no niveles.
CAUSAS: Final[dict[str, str]] = {
    "SIN_INFORMACION": (
        "El motor no pudo resolver: falta información del producto. "
        "Lo que se pide es completar el dato, no juzgar una fracción."
    ),
    "DESEMPATE_POR_NUMERACION": (
        "Se llegó a la RGI 3 c), que elige la última partida por orden de "
        "numeración. Aplica la regla correctamente y no distingue nada: entre "
        "una computadora y un monitor elegiría el monitor porque 8528 va "
        "después de 8471."
    ),
    "SIN_FRACCION_PROPUESTA": (
        "No hay fracción que confirmar. Revisar aquí es proponerla, no validar la del motor."
    ),
    "RESUELTA_PERO_MARCADA": (
        "El motor resolvió y aun así pidió revisión. La fracción propuesta es "
        "un punto de partida, no una conclusión."
    ),
}


def _normalizar(rule_id: str) -> str:
    """`RGI-3c`, `RGI3C` y `rgi 3 c` son la misma regla.

    El seed antiguo escribió `RGI1` sin guion y la traza del motor escribe
    `RGI-1`. Comparar en crudo dejaría casos sin causa según quién los
    escribiera, y un caso sin causa es justo lo que esta pantalla viene a
    eliminar.
    """
    return "".join(c for c in rule_id if c.isalnum()).upper()


def _causas(fila: ClassificationDecision) -> list[str]:
    """Por qué está este caso en la bandeja. Puede haber más de una razón."""
    encontradas: list[str] = []

    if fila.status == "INSUFFICIENT_INFORMATION":
        encontradas.append("SIN_INFORMACION")

    camino = {_normalizar(r) for r in (fila.rgi_path or [])}
    if _normalizar(REGLA_DESEMPATE) in camino:
        encontradas.append("DESEMPATE_POR_NUMERACION")

    if fila.fraction_code is None:
        encontradas.append("SIN_FRACCION_PROPUESTA")
    elif not encontradas:
        # Con fracción y sin ninguna otra causa, lo único que consta es que el
        # motor pidió revisión. Decirlo es mejor que dejar el caso mudo.
        encontradas.append("RESUELTA_PERO_MARCADA")

    return encontradas


class PendienteRead(ClassificationDecisionRead):
    """Una decisión esperando a una persona, con contexto para decidir."""

    producto: str | None = None
    """Nombre comercial, para no tener que abrir otra pantalla."""
    sku: str | None = None
    pasos_traza: int = 0
    """Cuántas reglas se evaluaron. Cero significa que no consta el
    razonamiento, y eso cambia cuánto puede fiarse quien revisa."""

    causas: list[str] = Field(default_factory=list)
    """Por qué está aquí. Lista, no valor único: las causas concurren.

    Vacía nunca debería estar — si lo está, el caso llegó a la bandeja por un
    camino que esta pantalla no sabe nombrar, y eso también es información.
    """

    causas_detalle: list[str] = Field(default_factory=list)
    """Qué se le pide al revisor en cada caso, en una frase."""


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
        causas = _causas(fila)
        detalle = PendienteRead.model_validate(fila, from_attributes=True)
        pendientes.append(
            detalle.model_copy(
                update={
                    "producto": producto.commercial_name if producto else None,
                    "sku": producto.sku if producto else None,
                    "pasos_traza": len(fila.rgi_trace or []),
                    "causas": causas,
                    "causas_detalle": [CAUSAS[c] for c in causas],
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
