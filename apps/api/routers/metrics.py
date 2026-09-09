"""Precisión de la clasificación, medida contra veredictos humanos (§39).

DE DÓNDE SALE LA VERDAD

No de `ground_truth_records`: esa tabla describe anomalías INYECTADAS en un
pedimento —`error_type`, `original_value`, `mutated_value`— y sirve para medir
detección, no acierto de clasificación. Un veredicto humano no cabe ahí sin
forzarlo.

Sale de un par de filas que ya existe por diseño. Cuando una persona revisa,
la bandeja NO sobrescribe la decisión de la máquina: crea una fila
`HUMAN_VALIDATED` que comparte `product_dna_id`. Se hizo así precisamente para
poder compararlas, y esa comparación es la métrica.

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
    porcentaje: Decimal | None = None
    """`None` cuando no hay nada comparado. No es cero: es desconocido."""


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
    """
    if humano is None:
        return None
    return maquina == humano


@router.get("/classification", summary="Precisión de la clasificación (§39)")
def precision(session: SessionDep) -> PrecisionClasificacion:
    """Compara cada veredicto humano con la decisión de máquina de su DNA."""
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

    # La decisión de máquina más reciente ANTERIOR al veredicto: es la que la
    # persona tenía delante cuando revisó. Emparejar con la última de todas
    # compararía el veredicto contra una clasificación que no vio.
    por_dna: dict[object, list[ClassificationDecision]] = {}
    for d in maquina:
        if d.product_dna_id is not None:
            por_dna.setdefault(d.product_dna_id, []).append(d)

    hs = Acierto()
    fraccion = Acierto()
    nico = Acierto()
    confirmadas = corregidas = 0

    for veredicto in humanos:
        candidatas = [
            d
            for d in por_dna.get(veredicto.product_dna_id, [])
            if d.created_at <= veredicto.created_at
        ]
        if not candidatas:
            continue
        original = candidatas[-1]

        for metrica, izq, der in (
            (hs, original.subheading, veredicto.subheading),
            (fraccion, original.fraction_code, veredicto.fraction_code),
            (nico, original.nico_code, veredicto.nico_code),
        ):
            resultado = _compara(izq, der)
            if resultado is None:
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

    pendientes = sum(1 for d in maquina if d.requires_human_review)

    return PrecisionClasificacion(
        hs_accuracy=hs,
        fraction_accuracy=fraccion,
        nico_accuracy=nico,
        human_review_rate=_porcentaje(pendientes + len(humanos), len(maquina)),
        decisiones_maquina=len(maquina),
        revisadas=len(humanos),
        pendientes_de_revision=pendientes,
        confirmadas=confirmadas,
        corregidas=corregidas,
    )
