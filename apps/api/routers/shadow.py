"""Pedimento Shadow (§32, §36) — lo declarado al lado de lo esperado.

LEE, NO REVISA

`POST /pedimentos/{id}/review` corre los motores y persiste. Esto sólo lee la
última corrida. Son cosas distintas a propósito: abrir una pantalla no debería
gastar llamadas a modelo ni escribir filas, y una auditoría es un evento que se
dispara, no un efecto de mirar.

LA REGLA QUE DEFINE ESTA PANTALLA

Una partida sin hallazgos NO está conforme. Puede estar conforme —se comprobó y
coincide— o puede estar sin verificar, que es lo contrario de una buena noticia.
`ShadowComparison` separa `divergences` de `unverifiable` justamente para que
nadie las colapse, y aquí esa separación llega hasta la fila de la tabla: cada
partida sale con uno de tres estados, nunca con dos.

Y hay un cuarto caso que tampoco se puede perder: una partida donde SÍ se
comprobó la fracción pero NO se pudo saber qué NOM exige. Tiene hallazgos y
tiene huecos a la vez. Se marca `verificacion_parcial` en vez de elegir uno de
los dos y callar el otro — presentar esa partida como «revisada» sería exacto en
la fracción y falso en el conjunto.

DE DÓNDE SALE «LO ESPERADO»

De los hallazgos persistidos: `risk_findings.expected_value` con
`field = 'tariff_fraction'`. El espejo completo vive en memoria durante la
corrida; lo que sobrevive en la base es la divergencia. Por eso, cuando una
partida es conforme, no hay expectativa que enseñar — y decir «esperado: igual
que lo declarado» sería inventarse una afirmación que nadie hizo.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
from database.models import Pedimento, PedimentoItem, RiskFinding, ShadowReview
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.db import SessionDep

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(prefix="/pedimentos", tags=["shadow"])

#: De más grave a menos. Mismo orden que el resto de la API.
ORDEN_SEVERIDAD: Final = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")

#: `core/shadow/compare.py` escribe cada motivo como «línea {n}: {razón}».
#: Se parsea para poder colgar cada motivo de su partida en la tabla. Si
#: alguien cambia ese formato, los motivos dejarían de atribuirse en silencio
#: —por eso `motivos_sin_atribuir` los conserva y un test fija el contrato
#: contra el motor de verdad, no contra una cadena escrita a mano.
_LINEA = re.compile(r"^\s*línea\s+(\d+)\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)

#: El campo con el que el espejo guarda la fracción esperada.
_CAMPO_FRACCION: Final = "tariff_fraction"


class DivergenciaRead(BaseModel):
    """Una diferencia concreta entre lo declarado y lo esperado."""

    finding_id: uuid.UUID
    finding_type: str
    field: str | None = None
    declared_value: str | None = None
    expected_value: str | None = None
    severity: str
    rationale: str | None = None
    impact_amount: Decimal | None = None
    """`None` = no se cuantificó. NO es cero: una NOM faltante no cambia lo
    que se paga y aun así detiene la mercancía."""
    impact_amount_currency: str | None = None
    is_simulation: bool = False


class LineaEspejo(BaseModel):
    """Una partida, con lo declarado y lo que el espejo esperaba."""

    line_number: int
    description: str
    product_id: uuid.UUID | None = None

    # ── lo declarado, tal cual viene en el pedimento ────────────────────────
    declared_fraction_code: str | None = None
    declared_nico_code: str | None = None
    country_of_origin: str | None = None
    customs_value: Decimal | None = None
    customs_value_currency: str | None = None

    # ── lo esperado ─────────────────────────────────────────────────────────
    expected_fraction_code: str | None = None
    """Sólo consta cuando hubo divergencia de fracción.

    `None` en una partida conforme NO significa «no se esperaba nada»: la
    expectativa coincidió y no dejó rastro. Repetir aquí lo declarado sería
    fabricar una confirmación que el motor nunca emitió.
    """

    # ── el veredicto ────────────────────────────────────────────────────────
    estado: str
    """`DIVERGENTE`, `SIN_VERIFICAR` o `CONFORME`. Nunca dos a la vez."""

    verificacion_parcial: bool = False
    """Hay hallazgos Y huecos: parte se comprobó y parte no.

    Sin esto, una partida con la fracción revisada y la NOM desconocida se
    presentaría como revisada — exacto en un campo, falso en el conjunto.
    """

    divergencias: list[DivergenciaRead] = Field(default_factory=list)
    no_verificable_por: list[str] = Field(default_factory=list)

    comprobado: list[str] = Field(default_factory=list)
    """Qué SÍ se comprobó de esta partida, por nombre.

    Es la mitad que faltaba. Sin ella, la pantalla sólo podía decir «conforme»
    o «sin verificar», y una partida con ocho comprobaciones buenas y dos
    imposibles se leía igual que una donde no se pudo comprobar nada — que es
    lo que hacía parecer que el sistema no verificaba nada.

    Enumerarlo NO afloja el §36: una partida no está limpia por tener ocho
    comprobaciones buenas si le faltan dos. Sólo deja de mentir sobre las ocho.
    """

    peor_severidad: str | None = None


class RevisionEspejo(BaseModel):
    """La corrida que se está leyendo."""

    review_id: uuid.UUID
    reviewed_at: datetime
    is_complete: bool
    """`False` = algo quedó sin comprobar. No es «casi limpio»."""
    engine_version: str | None = None
    data_origin: str


class PedimentoEspejo(BaseModel):
    """El pedimento declarado frente a su espejo (§36)."""

    pedimento_id: uuid.UUID
    pedimento_number: str
    operation_date: date
    """Manda sobre qué norma aplicaba (§14): el espejo se construyó con ella."""
    customs_office: str | None = None
    data_origin: str
    is_simulation: bool

    revision: RevisionEspejo | None = None
    """`None` = nunca se auditó. No es lo mismo que auditado sin hallazgos."""
    revisiones_totales: int = 0
    """Una auditoría es un evento: el mismo pedimento se revisa varias veces."""

    lineas: list[LineaEspejo] = Field(default_factory=list)

    partidas: int = 0
    divergentes: int = 0
    sin_verificar: int = 0
    conformes: int = 0
    """Sólo las que se comprobaron y coincidieron. Nada más puede llamarse así."""

    exposicion_cuantificada: Decimal | None = None
    """Suma SÓLO de los hallazgos con monto. Los demás no se estiman."""
    exposicion_moneda: str | None = None
    monedas_mezcladas: bool = False
    """Hay montos en más de una moneda: no se suman.

    Sumar pesos con dólares da un número que parece dinero y no lo es. Ante
    la duda no hay total, y se dice por qué.
    """
    hallazgos_sin_monto: int = 0

    motivos_sin_atribuir: list[str] = Field(default_factory=list)
    """Motivos de no-verificación que no se pudieron colgar de una partida.

    Debería estar vacío. Si no lo está, el formato del motor cambió y la
    pantalla lo dice en vez de perderlos.
    """


def _peor(severidades: list[str]) -> str | None:
    for nivel in ORDEN_SEVERIDAD:
        if nivel in severidades:
            return nivel
    return None


def _repartir_motivos(unverifiable: list[str]) -> tuple[dict[int, list[str]], list[str]]:
    """Cuelga cada motivo de su partida. Lo que no encaje se conserva aparte."""
    por_linea: dict[int, list[str]] = {}
    sueltos: list[str] = []
    for motivo in unverifiable:
        coincidencia = _LINEA.match(motivo)
        if coincidencia is None:
            sueltos.append(motivo)
            continue
        por_linea.setdefault(int(coincidencia.group(1)), []).append(coincidencia.group(2).strip())
    return por_linea, sueltos


def _ultima_revision(session: Session, pedimento_id: uuid.UUID) -> ShadowReview | None:
    return session.scalars(
        sa.select(ShadowReview)
        .where(ShadowReview.pedimento_id == pedimento_id)
        .order_by(ShadowReview.created_at.desc())
        .limit(1)
    ).first()


def _hallazgos(session: Session, revision: ShadowReview | None) -> list[RiskFinding]:
    """Los hallazgos DE ESA corrida, no todos los del pedimento.

    Sin filtrar por `shadow_review_id`, dos auditorías del mismo pedimento
    —antes y después de una rectificación— mezclarían sus hallazgos, y la
    pantalla enseñaría como vigente algo que ya se corrigió.
    """
    if revision is None:
        return []
    return list(
        session.scalars(
            sa.select(RiskFinding).where(RiskFinding.shadow_review_id == revision.id)
        ).all()
    )


def _estado(
    divergencias: list[DivergenciaRead],
    huecos: list[str],
    *,
    hubo_auditoria: bool,
    comprobadas: int = 0,
) -> str:
    """El estado de una partida. Nunca por descarte.

    `hubo_auditoria` no es un detalle: sin corrida del espejo, una partida no
    tiene divergencias ni huecos, y sin este parámetro caería en CONFORME.
    Un pedimento que nadie revisó pasaría por limpio — exactamente la
    confusión que esta pantalla existe para impedir. Lo detectó un test.

    PARCIAL, Y POR QUÉ HACÍA FALTA (Persona 1, 30-sep)

    Antes, CUALQUIER hueco mandaba la partida a SIN_VERIFICAR. Una con siete
    comprobaciones hechas y pasadas salía igual que una donde no se pudo
    comprobar nada, y las doce partidas del corpus se leían como si el sistema
    no verificara nada — cuando verificaba casi todo.

    Son estados distintos y ahora se distinguen:

        CONFORME       se comprobó todo lo comprobable y nada falló
        DIVERGENTE     algo se comprobó y no cuadró
        PARCIAL        parte se comprobó y pasó; otra parte no se pudo
        SIN_VERIFICAR  no se pudo comprobar NADA

    SIN_VERIFICAR sigue existiendo y sigue significando lo mismo de siempre:
    de esa partida no se puede afirmar nada. Lo que se deja de hacer es
    aplicarle esa etiqueta a partidas de las que sí se sabe bastante.
    """
    if not hubo_auditoria:
        return "SIN_VERIFICAR"
    if divergencias:
        return "DIVERGENTE"
    if not huecos:
        return "CONFORME"
    return "PARCIAL" if comprobadas else "SIN_VERIFICAR"


@router.get(
    "/{pedimento_id}/shadow",
    summary="El pedimento declarado frente a su espejo",
)
def espejo(pedimento_id: uuid.UUID, session: SessionDep) -> PedimentoEspejo:
    """Lee la última auditoría. No dispara una nueva."""
    pedimento = session.get(Pedimento, pedimento_id)
    if pedimento is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pedimento no encontrado")

    partidas = session.scalars(
        sa.select(PedimentoItem)
        .where(PedimentoItem.pedimento_id == pedimento_id)
        .order_by(PedimentoItem.line_number)
    ).all()

    revision = _ultima_revision(session, pedimento_id)
    total_revisiones = (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(ShadowReview)
            .where(ShadowReview.pedimento_id == pedimento_id)
        )
        or 0
    )

    hallazgos = _hallazgos(session, revision)
    por_partida: dict[uuid.UUID, list[RiskFinding]] = {}
    for h in hallazgos:
        if h.pedimento_item_id is not None:
            por_partida.setdefault(h.pedimento_item_id, []).append(h)

    motivos, sueltos = _repartir_motivos(list(revision.unverifiable) if revision else [])
    # `or []` no es defensa cosmética: las revisiones anteriores a esta columna
    # no la tienen, y una corrida vieja tiene que seguir leyéndose — sin
    # comprobaciones registradas, que es la verdad sobre ella.
    hechas, _ = _repartir_motivos(
        list(getattr(revision, "verified", None) or []) if revision else []
    )

    lineas: list[LineaEspejo] = []
    for partida in partidas:
        propios = por_partida.get(partida.id, [])
        divergencias = [
            DivergenciaRead(
                finding_id=h.id,
                finding_type=h.finding_type,
                field=h.field,
                declared_value=h.declared_value,
                expected_value=h.expected_value,
                severity=h.severity,
                rationale=h.rationale,
                impact_amount=h.impact_amount,
                impact_amount_currency=h.impact_amount_currency,
                is_simulation=h.is_simulation,
            )
            for h in propios
        ]
        huecos = motivos.get(partida.line_number, [])
        comprobadas = hechas.get(partida.line_number, [])
        esperada = next(
            (d.expected_value for d in divergencias if d.field == _CAMPO_FRACCION),
            None,
        )

        lineas.append(
            LineaEspejo(
                line_number=partida.line_number,
                description=partida.description,
                product_id=partida.product_id,
                declared_fraction_code=partida.declared_fraction_code,
                declared_nico_code=partida.declared_nico_code,
                country_of_origin=partida.country_of_origin,
                customs_value=partida.customs_value,
                customs_value_currency=partida.customs_value_currency,
                expected_fraction_code=esperada,
                estado=_estado(
                    divergencias,
                    huecos,
                    hubo_auditoria=revision is not None,
                    comprobadas=len(comprobadas),
                ),
                verificacion_parcial=bool(divergencias and huecos),
                divergencias=divergencias,
                no_verificable_por=huecos,
                comprobado=comprobadas,
                peor_severidad=_peor([d.severity for d in divergencias]),
            )
        )

    con_monto = [h for h in hallazgos if h.impact_amount is not None]
    monedas = {h.impact_amount_currency for h in con_monto if h.impact_amount_currency}
    mezcladas = len(monedas) > 1
    # UN monto por partida, no uno por hallazgo: dos divergencias de la misma
    # partida explican la MISMA diferencia y el motor le da a cada una el monto
    # entero (`core.audit.engine._total`). Sumarlos contaría ese dinero dos
    # veces, y con el corpus una partida puede traer valor y origen a la vez.
    monto_por_partida: dict[uuid.UUID, Decimal] = {}
    for h in con_monto:
        if h.impact_amount is None:
            continue
        clave = h.pedimento_item_id or h.id
        if abs(h.impact_amount) > abs(monto_por_partida.get(clave, Decimal(0))):
            monto_por_partida[clave] = h.impact_amount
    # Con más de una moneda no hay total: sumar pesos con dólares da un número
    # que parece dinero y no lo es.
    suma = (
        sum(monto_por_partida.values(), start=Decimal(0))
        if monto_por_partida and not mezcladas
        else None
    )

    return PedimentoEspejo(
        pedimento_id=pedimento.id,
        pedimento_number=pedimento.pedimento_number,
        operation_date=pedimento.operation_date,
        customs_office=pedimento.customs_office,
        data_origin=pedimento.data_origin,
        is_simulation=pedimento.is_simulation,
        revision=RevisionEspejo(
            review_id=revision.id,
            reviewed_at=revision.created_at,
            is_complete=revision.is_complete,
            engine_version=revision.engine_version,
            data_origin=revision.data_origin,
        )
        if revision
        else None,
        revisiones_totales=total_revisiones,
        lineas=lineas,
        partidas=len(partidas),
        divergentes=sum(1 for x in lineas if x.estado == "DIVERGENTE"),
        sin_verificar=sum(1 for x in lineas if x.estado == "SIN_VERIFICAR"),
        conformes=sum(1 for x in lineas if x.estado == "CONFORME"),
        exposicion_cuantificada=suma,
        exposicion_moneda=next(iter(monedas)) if len(monedas) == 1 else None,
        monedas_mezcladas=mezcladas,
        hallazgos_sin_monto=len(hallazgos) - len(con_monto),
        motivos_sin_atribuir=sueltos,
    )
