"""Precisión de la clasificación, medida contra veredictos humanos (§39).

DE DÓNDE SALE LA VERDAD

No de `ground_truth_records`: esa tabla describe anomalías INYECTADAS en un
pedimento —`error_type`, `original_value`, `mutated_value`— y sirve para medir
detección, no acierto de clasificación. Un veredicto humano no cabe ahí sin
forzarlo.

Sale de un par de filas que ya existe por diseño. Cuando una persona revisa,
la bandeja NO sobrescribe la decisión de la máquina: crea una fila
`HUMAN_VALIDATED` que apunta a ella por `reviews_decision_id`. Esa comparación
es la métrica.

EMPAREJAR POR PUNTERO, NO POR DNA Y TIEMPO

Hasta el 14 de septiembre se emparejaba cada veredicto con «la última decisión
de máquina del mismo DNA anterior al veredicto». En la compartida hay un DNA
con nueve decisiones y tres fechas de operación: el veredicto sobre el caso de
2024 se habría comparado contra la decisión de 2026, y dos veredictos sobre
casos distintos contra la misma. Ahora cada veredicto se compara con la
decisión a la que apunta, y nada más.

Las dos vías se complementan: `ground_truth_records` mide si el Espejo detecta
lo que se inyectó; esto mide si el motor clasifica como clasificaría una
persona.

UN CERO DECLARADO NO ES UN FALLO

Con la bandeja sin usar, la precisión no es «0 %»: es desconocida. Son cosas
distintas y confundirlas haría creer que el motor falla siempre cuando lo que
pasa es que nadie ha revisado. Por eso los porcentajes son `None` mientras no
haya pares, y la respuesta dice cuántos hay.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from database.models import ClassificationDecision
from fastapi import APIRouter
from pydantic import BaseModel, Field

from apps.api.db import SessionDep

router = APIRouter(prefix="/metrics", tags=["metrics"])

#: Lo que marca a una fila como veredicto humano.
ORIGEN_HUMANO = "HUMAN_VALIDATED"


class Acierto(BaseModel):
    """Una métrica de acierto, con lo que hay detrás del porcentaje."""

    aciertos: int = 0
    comparados: int = 0
    """Los casos donde LAS DOS PARTES declararon valor. Es el denominador."""
    abstenciones: int = 0
    """Los casos donde la persona declaró y el motor no.

    No entran en el porcentaje. Abstenerse no es fallar: el motor dijo que no
    podía, que es el comportamiento que §8.2 le exige cuando no tiene con qué.
    Contarlas como error mide otra cosa —cuánto le falta por cubrir— y la
    presenta como si midiera puntería.

    Es la misma regla que `_compara` ya aplicaba en el otro sentido: si la
    persona no declaró valor, no se puede saber si la máquina acertó. Nadie la
    había aplicado al revés, y por eso `fraction_accuracy` salía 0.00 % sobre
    13 casos cuando el motor sólo había contestado en uno.
    """
    porcentaje: Decimal | None = None
    """`None` cuando no hay nada comparado. No es cero: es desconocido."""


class ContraElMotorDeHoy(BaseModel):
    """Los veredictos humanos frente a la decisión VIGENTE de cada caso.

    No reasigna nada: `reviews_decision_id` sigue apuntando a la decisión que
    se revisó. Esto se calcula aparte, por ficha, con la misma unidad de caso
    que usa el tablero.
    """

    coinciden: int = 0
    """El motor contesta hoy lo mismo que dijo la persona."""
    discrepan: int = 0
    """El motor contesta hoy algo distinto. Es el número que importa vigilar."""
    se_abstiene: int = 0
    """La persona declaró y el motor de hoy no se atreve.

    No es un fallo: es §8.2. Pero sí es cobertura que falta, y por eso va
    aparte y no dentro de `coinciden`.
    """
    sin_caso: int = 0
    """El veredicto no cuelga de una ficha, así que no hay caso vigente que
    mirar. Se declara en vez de descartarlo en silencio."""

    @property
    def comparados(self) -> int:
        return self.coinciden + self.discrepan


class PrecisionClasificacion(BaseModel):
    """Las cuatro métricas de clasificación del §39."""

    hs_accuracy: Acierto = Field(default_factory=Acierto)
    """Coincide la subpartida (6 dígitos), que es lo armonizado
    internacionalmente. Acertar aquí y fallar la fracción es un error mexicano;
    fallar aquí es un error de fondo."""

    fraction_accuracy: Acierto = Field(default_factory=Acierto)
    """Coincide la fracción (8 dígitos). Es la que se declara en el pedimento."""

    nico_accuracy: Acierto = Field(default_factory=Acierto)
    """Coincide el NICO. Se compara sólo cuando la persona declaró uno."""

    human_review_rate: Decimal | None = None
    """Qué proporción de decisiones necesitó a una persona. `None` sin
    decisiones."""

    decisiones_maquina: int = 0
    revisadas: int = 0
    pendientes_de_revision: int = 0
    """La bandeja sin tocar. Es la cifra que dice por qué las demás están
    vacías."""

    confirmadas: int = 0
    corregidas: int = 0

    contra_el_motor_de_hoy: ContraElMotorDeHoy = Field(default_factory=lambda: ContraElMotorDeHoy())
    """Lo mismo, pero contra lo que el motor contesta AHORA.

    Las cuatro métricas de arriba comparan cada veredicto con la decisión que
    esa persona revisó, y hacen bien: es la traza de auditoría, dice qué dijo
    la máquina y qué dijo la persona ESE DÍA.

    El problema es presentarlas como la precisión del sistema. El único par
    comparable que hay hoy es la vajilla de cerámica del 28 de septiembre: el
    motor dijo 69120003 («De Talavera») y la persona 69120099 («Los demás»).
    `fraction_accuracy` sale 0.00 % por eso — y ese defecto se arregló el 28 de
    septiembre, el mismo día. El motor de hoy contesta 69120099 en ese caso.

    Así que ese 0 % es exacto y engaña: mide al motor **como era**, congelado
    en el momento en que alguien lo revisó, y nada en pantalla lo decía. Este
    bloque mide al motor **como está**, y las dos cifras responden preguntas
    distintas que las dos valen.
    """

    @property
    def hay_con_que_medir(self) -> bool:
        return self.revisadas > 0


def _porcentaje(aciertos: int, total: int) -> Decimal | None:
    """Redondeado a dos decimales. `None` si no hay nada que dividir.

    Decimal y no float: §22 dice que lo que se presenta como cifra no se
    calcula con coma flotante, y una precisión que se muestra a un cliente
    entra en esa categoría.
    """
    if total == 0:
        return None
    return (Decimal(aciertos) / Decimal(total) * 100).quantize(Decimal("0.01"))


def _compara(maquina: str | None, humano: str | None) -> bool | None:
    """¿Coinciden? `None` cuando no hay con qué comparar.

    Si la persona no declaró valor, no se puede saber si la máquina acertó —
    y contarlo como fallo castigaría al motor por un dato que nadie dio.

    Y AL REVÉS, que es lo que faltaba: si el MOTOR no declaró valor, tampoco se
    puede decir que se equivocó. Se abstuvo, que es lo que §8.2 le exige cuando
    no tiene con qué. Quien llama las cuenta aparte.
    """
    if humano is None or maquina is None:
        return None
    return maquina == humano


@router.get("/classification", summary="Precisión de la clasificación (§39)")
def precision(session: SessionDep) -> PrecisionClasificacion:
    """Compara cada veredicto humano con la decisión de máquina que revisó."""
    humanos = session.scalars(
        sa.select(ClassificationDecision)
        .where(ClassificationDecision.data_origin == ORIGEN_HUMANO)
        .order_by(ClassificationDecision.created_at)
    ).all()

    maquina = session.scalars(
        sa.select(ClassificationDecision)
        .where(ClassificationDecision.data_origin != ORIGEN_HUMANO)
        .order_by(ClassificationDecision.created_at)
    ).all()

    por_id = {d.id: d for d in maquina}

    hs = Acierto()
    fraccion = Acierto()
    nico = Acierto()
    confirmadas = corregidas = 0
    revisadas: set[object] = set()

    for veredicto in humanos:
        # La decisión que ESTE veredicto revisó. Si no apunta a ninguna decisión
        # de máquina conocida no hay con qué comparar, y no se inventa un par.
        original = (
            por_id.get(veredicto.reviews_decision_id)
            if veredicto.reviews_decision_id is not None
            else None
        )
        if original is None:
            continue
        revisadas.add(original.id)

        for metrica, izq, der in (
            (hs, original.subheading, veredicto.subheading),
            (fraccion, original.fraction_code, veredicto.fraction_code),
            (nico, original.nico_code, veredicto.nico_code),
        ):
            resultado = _compara(izq, der)
            if resultado is None:
                # La persona declaró y el motor no: es una abstención, no un
                # fallo. Se cuenta aparte para que el porcentaje mida puntería
                # y este número mida cobertura, que son cosas distintas.
                if der is not None and izq is None:
                    metrica.abstenciones += 1
                continue
            metrica.comparados += 1
            if resultado:
                metrica.aciertos += 1

        if original.fraction_code == veredicto.fraction_code:
            confirmadas += 1
        else:
            corregidas += 1

    for metrica in (hs, fraccion, nico):
        metrica.porcentaje = _porcentaje(metrica.aciertos, metrica.comparados)

    hoy = _contra_el_motor_de_hoy(humanos, maquina)

    pendientes = sum(1 for d in maquina if d.requires_human_review)
    # Decisiones DISTINTAS que necesitaron a una persona: las que esperan y las
    # ya revisadas. Por decisión y no por fila de veredicto, para que la tasa
    # no pueda pasar del 100 %.
    necesitaron = {d.id for d in maquina if d.requires_human_review} | revisadas

    return PrecisionClasificacion(
        hs_accuracy=hs,
        fraction_accuracy=fraccion,
        nico_accuracy=nico,
        human_review_rate=_porcentaje(len(necesitaron), len(maquina)),
        decisiones_maquina=len(maquina),
        revisadas=len(revisadas),
        pendientes_de_revision=pendientes,
        confirmadas=confirmadas,
        corregidas=corregidas,
        contra_el_motor_de_hoy=hoy,
    )


def _contra_el_motor_de_hoy(
    humanos: Sequence[ClassificationDecision],
    maquina: Sequence[ClassificationDecision],
) -> ContraElMotorDeHoy:
    """Los veredictos frente a la decisión VIGENTE de su caso.

    POR QUÉ ESTE BLOQUE EXISTE

    Las métricas de arriba comparan cada veredicto con la decisión que esa
    persona revisó. Eso es la traza de auditoría y no se toca. Pero como
    precisión del sistema engaña: el único par comparable hoy es la vajilla del
    28 de septiembre, cuyo defecto se arregló ese mismo día. `fraction_accuracy
    = 0.00 %` mide al motor como era, y nada lo decía.

    Aquí la unidad es el caso —`product_dna_id`, igual que en el tablero—,
    porque el veredicto es sobre la mercancía: mientras la ficha sea la misma,
    lo que esa persona dijo sigue dicho.

    No se reasigna nada. `reviews_decision_id` sigue apuntando donde apuntaba.
    """
    vigente: dict[object, ClassificationDecision] = {}
    for d in maquina:
        if d.product_dna_id is None:
            continue
        previa = vigente.get(d.product_dna_id)
        if previa is None or d.created_at > previa.created_at:
            vigente[d.product_dna_id] = d

    salida = ContraElMotorDeHoy()
    for veredicto in humanos:
        if veredicto.fraction_code is None:
            continue
        actual = (
            vigente.get(veredicto.product_dna_id) if veredicto.product_dna_id is not None else None
        )
        if actual is None:
            salida.sin_caso += 1
        elif actual.fraction_code is None:
            salida.se_abstiene += 1
        elif actual.fraction_code == veredicto.fraction_code:
            salida.coinciden += 1
        else:
            salida.discrepan += 1
    return salida
