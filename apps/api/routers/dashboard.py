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
from database.repositories.findings import de_la_ultima_revision
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
    dictaminadas: int = 0
    """Sobre las que YA se pronunció un clasificador.

    Atraviesa a las demás en vez de excluirlas: una decisión puede estar
    resuelta Y dictaminada, y por eso los cuatro números pueden sumar más que
    el total. Forzar categorías exclusivas escondería justo el caso que más
    interesa —la máquina resolvió y una persona lo confirmó o lo corrigió—.

    Sin esto las cifras no sumaban —11 decisiones, 2 resueltas, 2 esperando— y
    los 7 casos que faltaban eran justo los que más valen: la única verdad del
    sistema que no generamos nosotros.
    """
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
    por_severidad: dict[str, int] = Field(default_factory=dict)
    """Cuántos hay de cada severidad.

    `peor_severidad` sola no dice nada: un CRITICAL entre ochenta y ocho y
    ochenta y ocho CRITICAL se leen igual, y no son lo mismo. Enseñar el
    reparto convierte una palabra que alarma en información que se puede usar
    —y evita que quien mira el tablero crea que el alarmado es el sistema y no
    los pedimentos que audita.
    """

    accionables: int = 0
    """Con impacto cuantificado: se pueden llevar a un cliente."""
    solo_investigables: int = 0
    """Sin monto. NO son menos graves — una NOM faltante no cambia lo que se
    paga y aun así detiene la mercancía."""
    impacto_cuantificado: Decimal | None = None
    """Suma SÓLO de los hallazgos con monto. Los demás no se estiman.

    `None` cuando hay más de una moneda: ver `monedas_mezcladas`.
    """
    impacto_moneda: str | None = None
    sobrepagos: int = 0
    """Hallazgos cuyo monto es negativo: se pagó de más.

    No entran en `impacto_cuantificado`, porque restarlos de la exposición
    daría un neto que no es ni lo que se debe ni lo que se puede recuperar. Se
    cuentan aquí para que no desaparezcan: el importe está en la tarjeta de
    Oportunidad, que es donde esa conversación tiene sentido.
    """

    monedas_mezcladas: bool = False
    """Hay montos en más de una moneda, así que no hay total.

    El Espejo ya aplicaba esta disciplina (`PedimentoEspejo.monedas_mezcladas`)
    y el tablero no: sumaba a ciegas y etiquetaba el resultado con la PRIMERA
    moneda que encontraba. Con dos monedas eso da un número que parece dinero,
    no lo es, y encima lleva una divisa que afirma de qué moneda es. Ante la
    duda no hay total, y se dice por qué.
    """


class Oportunidades(BaseModel):
    """Dinero recuperable, que es otra conversación con el cliente."""

    total: int = 0
    ahorro_cuantificado: Decimal | None = None
    ahorro_moneda: str | None = None
    monedas_mezcladas: bool = False
    """Mismo criterio que en los hallazgos: con dos monedas no hay total."""
    simuladas: int = 0
    """Cuántas de esas oportunidades salen de un pedimento simulado.

    Un ahorro es el dato de esta consola que alguien querría cobrar. Que no
    dijera si sale de una operación inventada era la regla 4 al revés, y el
    censo de `filas_simuladas` ni siquiera contaba esta tabla.
    """


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

    SÓLO LO QUE SE DEBE, NO LO QUE SE PAGÓ DE MÁS (Persona 1, 5-oct)

    Un sobrepago llega con monto negativo, y sumado a la exposición la resta.
    Un pedimento que dejó de pagar 50 000 y pagó 30 000 de más mostraba 20 000
    de exposición: ni los 50 000 que hay que regularizar ni los 30 000 que se
    pueden recuperar, sino un neto que no es ninguna de las dos cosas y que
    nadie puede presentar.

    Son dos conversaciones distintas con el cliente —«esto lo debes» y «esto lo
    puedes recuperar»— y el dinero recuperable ya tiene su tarjeta: el Money
    Finder lo emite como oportunidad, en positivo. Aquí se cuenta sólo lo que
    se debe, y los sobrepagos se declaran por número en `sobrepagos` para que
    no desaparezcan en silencio.
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
            # `> 0` ya excluye el nulo y el cero; se deja explícito porque lo
            # que esta condición significa es «lo que se debe», no «lo que
            # tiene monto».
            RiskFinding.impact_amount > 0,
            sa.or_(
                RiskFinding.shadow_review_id.is_(None),
                RiskFinding.shadow_review_id.in_(sa.select(ultimas.c.id)),
            ),
        )
        .group_by(sa.func.coalesce(RiskFinding.pedimento_item_id, RiskFinding.id))
        .subquery()
    )


def _la_decision_vigente() -> sa.ColumnElement[bool]:
    """La última decisión de cada ficha, no todas las que hubo.

    Clasificar otra vez el mismo producto no es otro caso: es el mismo caso
    con una respuesta nueva. Las decisiones sin ficha pasan una a una —sin
    `product_dna_id` no hay por qué agruparlas, y descartarlas perdería casos
    en silencio.
    """
    otra = sa.orm.aliased(ClassificationDecision, name="otra_decision")
    reciente = (
        sa.select(sa.func.max(otra.created_at))
        .where(
            otra.product_dna_id == ClassificationDecision.product_dna_id,
            otra.data_origin != "HUMAN_VALIDATED",
        )
        .scalar_subquery()
    )
    return sa.and_(
        # Un veredicto humano no es una decisión del motor: describe lo que
        # hizo una persona sobre ella. Contarlo aquí haría que un caso
        # dictaminado desapareciera de «esperan» por la puerta equivocada —lo
        # que lo saca es `requires_human_review`, que la revisión pone en
        # falso, igual que en la bandeja (#131).
        ClassificationDecision.data_origin != "HUMAN_VALIDATED",
        sa.or_(
            ClassificationDecision.product_dna_id.is_(None),
            ClassificationDecision.created_at == reciente,
        ),
    )


def _ya_dictaminada() -> sa.ColumnElement[bool]:
    """¿Existe un veredicto humano que apunte a esta decisión?

    Se pregunta por el veredicto y no por `requires_human_review`: ese campo
    también es falso en las que el motor resolvió limpio y nadie miró, que es
    otra cosa muy distinta.
    """
    veredicto = sa.orm.aliased(ClassificationDecision, name="veredicto")
    return sa.exists(
        sa.select(veredicto.id).where(veredicto.reviews_decision_id == ClassificationDecision.id)
    )


def _contar(session: SessionDep, modelo: type, *filtros: sa.ColumnElement) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(modelo).where(*filtros)) or 0


@router.get("", summary="Cifras del sistema")
def tablero(session: SessionDep) -> Dashboard:
    """Todo en una respuesta: un tablero que se pinta a trozos parpadea."""
    # UN PRODUCTO ES UN CASO, NO UNA FILA POR CADA VEZ QUE SE CLASIFICÓ
    #
    # Contando decisiones, el tablero anunciaba 24 «esperando a una persona»
    # mientras la bandeja enseñaba 9: cada re-clasificación del mismo producto
    # —por una prueba, por un cambio del motor— dejaba otra fila pendiente.
    # «Esperan a una persona» es trabajo, y el trabajo son casos.
    #
    # Se cuenta el estado VIGENTE de cada ficha, con el mismo criterio que la
    # bandeja (#131). Quinta vez que aparece el patrón en el proyecto.
    vigente = _la_decision_vigente()
    decisiones = Clasificaciones(
        total=_contar(session, ClassificationDecision, vigente),
        resueltas=_contar(
            session, ClassificationDecision, vigente, ClassificationDecision.status == "RESOLVED"
        ),
        # El mismo criterio que la bandeja: lo que sigue esperando es lo que
        # NADIE ha dictaminado todavía. Con `status` a secas, un caso ya
        # revisado seguiría contando como pendiente para siempre.
        requieren_revision=_contar(
            session,
            ClassificationDecision,
            vigente,
            ClassificationDecision.requires_human_review.is_(True),
        ),
        sin_informacion=_contar(
            session,
            ClassificationDecision,
            vigente,
            ClassificationDecision.status == "INSUFFICIENT_INFORMATION",
        ),
        dictaminadas=_contar(session, ClassificationDecision, vigente, _ya_dictaminada()),
        con_traza=_contar(
            session, ClassificationDecision, vigente, ClassificationDecision.rgi_trace.isnot(None)
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

    # EL TABLERO CUENTA EL ESTADO ACTUAL, NO LA SUMA DE LAS AUDITORÍAS
    #
    # `total_hallazgos` contaba TODOS los `RiskFinding`, y cada re-auditoría
    # deja los suyos: con 106 revisiones acumuladas el tablero anunciaba 467
    # hallazgos donde las revisiones vigentes tienen 89. Cinco veces la cifra
    # real, y creciendo cada vez que alguien volvía a medir.
    #
    # Lo peor no era el número: era que el tablero se contradecía. La
    # exposición YA se acotaba a la última revisión desde el #100, así que
    # convivían un importe del estado actual y un conteo del histórico en la
    # misma pantalla.
    #
    # Cuarta vez que aparece este patrón —#100 en la exposición, #120 en los
    # hallazgos, #131 en la bandeja y ahora aquí—. Por eso el predicado vive en
    # `database.repositories.findings` y se importa, en vez de reescribirse.
    vigentes = de_la_ultima_revision()
    con_monto = sa.and_(RiskFinding.impact_amount.isnot(None), RiskFinding.impact_amount != 0)
    total_hallazgos = _contar(session, RiskFinding, vigentes)
    accionables = _contar(session, RiskFinding, vigentes, con_monto)
    # Los sobrepagos no entran en la exposición, pero se dicen por número: un
    # hallazgo que desaparece de la pantalla sin explicación es peor que uno
    # que se declara fuera del total.
    sobrepagos = _contar(session, RiskFinding, vigentes, RiskFinding.impact_amount < 0)
    # Las monedas presentes, no «la primera»: con dos, no hay total que dar.
    # Las de lo que SE DEBE, que es lo que se suma — una moneda que sólo
    # aparece en un sobrepago no puede invalidar el total de la exposición.
    monedas_hallazgos = {
        m
        for m in session.scalars(
            sa.select(RiskFinding.impact_amount_currency)
            .where(vigentes, RiskFinding.impact_amount > 0)
            .distinct()
        )
        if m
    }
    mezcla_hallazgos = len(monedas_hallazgos) > 1
    suma = (
        None if mezcla_hallazgos else session.scalar(sa.select(sa.func.sum(_por_partida().c.monto)))
    )
    moneda = next(iter(monedas_hallazgos)) if len(monedas_hallazgos) == 1 else None
    reparto = {
        fila.severity: fila.cuantos
        for fila in session.execute(
            sa.select(RiskFinding.severity, sa.func.count().label("cuantos"))
            .where(vigentes)
            .group_by(RiskFinding.severity)
        )
        if fila.severity
    }
    peor = session.scalar(
        sa.select(RiskFinding.severity)
        .where(vigentes)
        .order_by(
            sa.case(
                {s: i for i, s in enumerate(ORDEN_SEVERIDAD)},
                value=RiskFinding.severity,
                else_=len(ORDEN_SEVERIDAD),
            )
        )
        .limit(1)
    )

    con_ahorro = OpportunityFinding.estimated_saving_amount.isnot(None)
    monedas_ahorro = {
        m
        for m in session.scalars(
            sa.select(OpportunityFinding.estimated_saving_amount_currency)
            .where(con_ahorro)
            .distinct()
        )
        if m
    }
    mezcla_ahorro = len(monedas_ahorro) > 1
    ahorro = (
        None
        if mezcla_ahorro
        else session.scalar(sa.select(sa.func.sum(OpportunityFinding.estimated_saving_amount)))
    )
    ahorro_moneda = next(iter(monedas_ahorro)) if len(monedas_ahorro) == 1 else None

    # Los hallazgos van acotados aquí también, o el pie compararía poblaciones
    # distintas: «N de las filas contadas son simulación» con una N del
    # histórico y un total del estado actual no dice nada.
    simuladas = sum(
        _contar(session, modelo, modelo.data_origin == "SYNTHETIC")  # type: ignore[attr-defined]
        for modelo in (Product, Pedimento, ClassificationDecision)
    ) + _contar(session, RiskFinding, vigentes, RiskFinding.data_origin == "SYNTHETIC")
    # Las oportunidades no entraban en el censo, así que un ahorro simulado no
    # contaba para `todo_simulado`: bastaba cargar un producto real para que el
    # aviso desapareciera y el dinero inventado se quedara en pantalla sin
    # marca ninguna.
    oportunidades_simuladas = _contar(
        session, OpportunityFinding, OpportunityFinding.is_simulation.is_(True)
    )
    total_oportunidades = _contar(session, OpportunityFinding)
    simuladas += oportunidades_simuladas
    contadas = (
        pedimentos
        + decisiones.total
        + total_hallazgos
        + _contar(session, Product)
        + total_oportunidades
    )

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
            por_severidad=reparto,
            accionables=accionables,
            solo_investigables=total_hallazgos - accionables,
            impacto_cuantificado=suma,
            impacto_moneda=moneda,
            sobrepagos=sobrepagos,
            monedas_mezcladas=mezcla_hallazgos,
        ),
        oportunidades=Oportunidades(
            total=total_oportunidades,
            ahorro_cuantificado=ahorro,
            ahorro_moneda=ahorro_moneda,
            monedas_mezcladas=mezcla_ahorro,
            simuladas=oportunidades_simuladas,
        ),
        productos=_contar(session, Product),
        filas_simuladas=simuladas,
        todo_simulado=contadas > 0 and simuladas == contadas,
    )
