"""Tablero ejecutivo (§32).

Es lo primero que ve alguien del cliente, y por eso es donde más tienta redondear.
No lo hace: cada cifra sale de contar filas reales, y las que no se pueden
sostener no se inventan.

TRES REGLAS QUE LO DEFINEN

1. **Nada de estimaciones globales.** Un «ahorro potencial detectado» que sume
   hallazgos sin confirmar es un número de folleto: se presenta como si fuera
   dinero recuperable y no lo es. Aquí sólo se suma lo cuantificado.

2. **Lo pendiente es tan importante como lo hecho.** Cuántas decisiones
   esperan revisión humana y cuántos pedimentos nadie ha auditado dicen más
   del estado real que el total de clasificaciones.

3. **El mismo dinero no se cuenta dos veces**, ni entre las divergencias de
   una partida ni entre auditorías repetidas del mismo pedimento. Una partida con la fracción y
   el valor equivocados produce DOS hallazgos, y el motor atribuye a cada uno
   el monto entero a propósito: cada causa explica la diferencia por completo
   (`core.audit.engine._total`). Sumar los montos fila por fila contaría ese
   delta dos veces, y con el corpus —donde una partida puede tener divergencia
   de valor y de origen— el tablero enseñaría más dinero del que existe. Se
   suma UN monto por partida.

4. **`SYNTHETIC` se cuenta aparte.** §33: si una cifra mezcla datos simulados
   con reales, deja de poder presentarse. El tablero declara cuántas de sus
   filas son simulación.
"""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from database.models import (
    ClassificationDecision,
    OpportunityFinding,
    Pedimento,
    Product,
    RiskFinding,
    ShadowReview,
)
from fastapi import APIRouter
from pydantic import BaseModel, Field

from apps.api.db import SessionDep

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

#: De más grave a menos, para elegir la peor presente.
ORDEN_SEVERIDAD = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")


class Clasificaciones(BaseModel):
    """Qué ha podido resolver el motor, y qué no."""

    total: int = 0
    resueltas: int = 0
    requieren_revision: int = 0
    """Ni error ni éxito: es trabajo esperando a una persona."""
    sin_informacion: int = 0
    """El motor no pudo, y saberlo vale tanto como el código cuando sí puede."""
    con_traza: int = 0
    """De cuántas se conservó el razonamiento paso a paso."""


class Auditoria(BaseModel):
    """Qué se ha revisado de verdad."""

    pedimentos: int = 0
    auditados: int = 0
    """Con al menos una revisión registrada."""
    sin_auditar: int = 0
    """Nadie los ha mirado. No están limpios: están sin revisar."""
    auditados_completos: int = 0
    """Los únicos de los que se puede afirmar que están limpios."""


class Hallazgos(BaseModel):
    """Riesgo detectado, separando lo presentable de lo investigable."""

    total: int = 0
    peor_severidad: str | None = None
    accionables: int = 0
    """Con impacto cuantificado: se pueden llevar a un cliente."""
    solo_investigables: int = 0
    """Sin monto. NO son menos graves — una NOM faltante no cambia lo que se
    paga y aun así detiene la mercancía."""
    impacto_cuantificado: Decimal | None = None
    """Suma SÓLO de los hallazgos con monto. Los demás no se estiman."""
    impacto_moneda: str | None = None


class Oportunidades(BaseModel):
    """Dinero recuperable, que es otra conversación con el cliente."""

    total: int = 0
    ahorro_cuantificado: Decimal | None = None
    ahorro_moneda: str | None = None


class Dashboard(BaseModel):
    """El estado del sistema en cifras que se pueden defender."""

    clasificaciones: Clasificaciones = Field(default_factory=Clasificaciones)
    auditoria: Auditoria = Field(default_factory=Auditoria)
    hallazgos: Hallazgos = Field(default_factory=Hallazgos)
    oportunidades: Oportunidades = Field(default_factory=Oportunidades)

    productos: int = 0

    filas_simuladas: int = 0
    """Cuántas de las filas contadas son `SYNTHETIC` (§33).

    Se declara en vez de mezclarlas en silencio: una cifra que suma datos
    simulados y reales deja de poder presentarse.
    """
    todo_simulado: bool = True
    """¿Absolutamente todo lo contado es simulación?

    Mientras sea `true`, el tablero entero se marca SYNTHETIC DEMO DATA.
    """


def _por_partida() -> sa.Subquery:
    """Un monto por partida, no uno por hallazgo.

    Varias divergencias de la misma partida explican la MISMA diferencia de
    contribuciones, y el motor le atribuye a cada una el monto entero
    (`core.audit.engine`). Se agrupa por partida y se toma el mayor, que es
    exactamente lo que hace `_total` dentro del motor.

    Los hallazgos sin partida —el del seed, por ejemplo— se agrupan por su
    propio id: no se pierden, y cada uno cuenta una vez.

    Y SÓLO LA ÚLTIMA REVISIÓN DE CADA PEDIMENTO (Persona 1, 22-sep): la
    exposición de un pedimento no es la suma de las veces que lo hemos mirado.
    Auditarlo dos veces no lo hace deber el doble.

    Los hallazgos sin revisión —el del seed— siguen contando: son un hecho
    registrado aunque no conste de qué corrida salieron.
    """
    ultimas = (
        sa.select(ShadowReview.id)
        .distinct(ShadowReview.pedimento_id)
        .order_by(ShadowReview.pedimento_id, ShadowReview.created_at.desc())
        .subquery()
    )
    monto = sa.func.max(RiskFinding.impact_amount).label("monto")
    return (
        sa.select(monto)
        .where(
            RiskFinding.impact_amount.isnot(None),
            RiskFinding.impact_amount != 0,
            sa.or_(
                RiskFinding.shadow_review_id.is_(None),
                RiskFinding.shadow_review_id.in_(sa.select(ultimas.c.id)),
            ),
        )
        .group_by(sa.func.coalesce(RiskFinding.pedimento_item_id, RiskFinding.id))
        .subquery()
    )


def _contar(session: SessionDep, modelo: type, *filtros: sa.ColumnElement) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(modelo).where(*filtros)) or 0


@router.get("", summary="Cifras del sistema")
def tablero(session: SessionDep) -> Dashboard:
    """Todo en una respuesta: un tablero que se pinta a trozos parpadea."""
    decisiones = Clasificaciones(
        total=_contar(session, ClassificationDecision),
        resueltas=_contar(
            session, ClassificationDecision, ClassificationDecision.status == "RESOLVED"
        ),
        requieren_revision=_contar(
            session,
            ClassificationDecision,
            ClassificationDecision.status == "HUMAN_REVIEW_REQUIRED",
        ),
        sin_informacion=_contar(
            session,
            ClassificationDecision,
            ClassificationDecision.status == "INSUFFICIENT_INFORMATION",
        ),
        con_traza=_contar(
            session, ClassificationDecision, ClassificationDecision.rgi_trace.isnot(None)
        ),
    )

    pedimentos = _contar(session, Pedimento)
    auditados = (
        session.scalar(sa.select(sa.func.count(sa.distinct(ShadowReview.pedimento_id)))) or 0
    )
    completos = (
        session.scalar(
            sa.select(sa.func.count(sa.distinct(ShadowReview.pedimento_id))).where(
                ShadowReview.is_complete.is_(True)
            )
        )
        or 0
    )

    con_monto = sa.and_(RiskFinding.impact_amount.isnot(None), RiskFinding.impact_amount != 0)
    total_hallazgos = _contar(session, RiskFinding)
    accionables = _contar(session, RiskFinding, con_monto)
    suma = session.scalar(sa.select(sa.func.sum(_por_partida().c.monto)))
    moneda = session.scalar(sa.select(RiskFinding.impact_amount_currency).where(con_monto).limit(1))
    peor = session.scalar(
        sa.select(RiskFinding.severity)
        .order_by(
            sa.case(
                {s: i for i, s in enumerate(ORDEN_SEVERIDAD)},
                value=RiskFinding.severity,
                else_=len(ORDEN_SEVERIDAD),
            )
        )
        .limit(1)
    )

    ahorro = session.scalar(sa.select(sa.func.sum(OpportunityFinding.estimated_saving_amount)))
    ahorro_moneda = session.scalar(
        sa.select(OpportunityFinding.estimated_saving_amount_currency)
        .where(OpportunityFinding.estimated_saving_amount.isnot(None))
        .limit(1)
    )

    simuladas = sum(
        _contar(session, modelo, modelo.data_origin == "SYNTHETIC")  # type: ignore[attr-defined]
        for modelo in (Product, Pedimento, ClassificationDecision, RiskFinding)
    )
    contadas = pedimentos + decisiones.total + total_hallazgos + _contar(session, Product)

    return Dashboard(
        clasificaciones=decisiones,
        auditoria=Auditoria(
            pedimentos=pedimentos,
            auditados=auditados,
            sin_auditar=pedimentos - auditados,
            auditados_completos=completos,
        ),
        hallazgos=Hallazgos(
            total=total_hallazgos,
            peor_severidad=peor,
            accionables=accionables,
            solo_investigables=total_hallazgos - accionables,
            impacto_cuantificado=suma,
            impacto_moneda=moneda,
        ),
        oportunidades=Oportunidades(
            total=_contar(session, OpportunityFinding),
            ahorro_cuantificado=ahorro,
            ahorro_moneda=ahorro_moneda,
        ),
        productos=_contar(session, Product),
        filas_simuladas=simuladas,
        todo_simulado=contadas > 0 and simuladas == contadas,
    )
