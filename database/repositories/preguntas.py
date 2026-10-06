"""Qué casos esperan a una persona, y qué preguntas los desatascarían.

UNA SOLA DEFINICIÓN DE «PENDIENTE», Y POR QUÉ TUVO QUE VENIR AQUÍ

Hasta el 6-oct había tres, y no coincidían (Persona 3, verificado por
Persona 1):

    · la bandeja (`GET /review`): `requires_human_review`, la última decisión
      de cada `product_dna_id`, cortada en una página de 50;
    · el script de la terminal: `status = 'HUMAN_REVIEW_REQUIRED'`, la última
      de cada `product_id`;
    · el recálculo al contestar: TODAS las pendientes, no sólo la última.

Con tres conjuntos distintos, la tarjeta de una pregunta podía decir «14
casos» mientras la bandeja enseñaba 12 y el recálculo tocaba otros. Quien
contesta vería un número que no se cumple y concluiría —con razón— que su
respuesta no sirvió.

La correcta es la de la bandeja, pieza a pieza:

    · `requires_human_review` y no `status`: el estado deja fuera las
      INSUFFICIENT_INFORMATION y las RGI 3 c) resueltas pero marcadas. La
      bandera es lo que significa «una persona tiene que mirarlo».
    · la última por `product_dna_id`: el estado actual es el último evento, no
      la unión de todos (#100, #120). Y la identidad del caso es la ficha.
    · sin límite: 50 es una página, no una definición. Contar sobre una página
      haría decir 14 donde son 20.

LAS PREGUNTAS SON LAS QUE DEJÓ EL MOTOR, SIN FILTRO PROPIO

Se leen tal cual de `rgi_trace[-1].preguntas`. El script filtraba además las
«ya contestadas» comparando sólo el lado de la tarifa — el defecto exacto que
`core.rgi_engine.pregunta._ya_esta_contestada` existe para evitar: una
respuesta sobre tuberías callaba la pregunta de un sartén. Decidir qué se
pregunta es del motor; aquí sólo se agrupa.

Vive en un repositorio porque lo usan la API y la evaluación, que no se
importan entre sí (mismo criterio que `findings.py`).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, aliased

from database.models import ClassificationDecision, Product

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable, Sequence


def pendientes_vigentes() -> sa.Select[tuple[ClassificationDecision]]:
    """Los casos que esperan a una persona: una decisión por ficha, la última.

    Las decisiones sin ficha pasan una a una: sin `product_dna_id` no hay por
    qué agruparlas, y descartarlas sería perder casos en silencio.
    """
    otra = aliased(ClassificationDecision, name="otra")
    reciente = (
        sa.select(sa.func.max(otra.created_at))
        .where(otra.product_dna_id == ClassificationDecision.product_dna_id)
        .scalar_subquery()
    )
    return sa.select(ClassificationDecision).where(
        ClassificationDecision.requires_human_review.is_(True),
        # Las revisiones humanas no vuelven a la bandeja.
        ClassificationDecision.data_origin != "HUMAN_VALIDATED",
        sa.or_(
            ClassificationDecision.product_dna_id.is_(None),
            ClassificationDecision.created_at == reciente,
        ),
    )


def preguntas_de(decision: ClassificationDecision) -> list[dict[str, Any]]:
    """Las preguntas del último paso de la traza, si las hay.

    El último paso es donde el motor se atascó: los anteriores continuaron, y
    preguntar por una regla que ya pasó no desatasca nada.
    """
    traza = decision.rgi_trace or []
    if not traza or not isinstance(traza[-1], dict):
        return []
    return [
        q
        for q in traza[-1].get("preguntas") or []
        if isinstance(q, dict) and q.get("codigo") and q.get("exige")
    ]


@dataclass(frozen=True)
class PreguntaPendiente:
    """Una cláusula sin contestar y los casos que la tienen delante."""

    codigo: str
    """La posición que no se pudo descartar."""
    exige: str
    """Lo que esa posición exige. Es la clave con la que se guarda la respuesta."""
    texto: str
    """La pregunta escrita para una persona, tal como la formuló el motor."""
    decisiones: tuple[ClassificationDecision, ...]
    """Los casos, una decisión vigente cada uno."""
    fichas: tuple[str, ...]
    """Lo que dicen las fichas de esos casos, sin repetir.

    Si son varias, la respuesta puede no valer igual para todas: se aplica a
    las fichas que digan el término elegido, y quien contesta tiene que verlo.
    """


def agrupar(decisiones: Iterable[ClassificationDecision]) -> list[PreguntaPendiente]:
    """Las preguntas, agrupadas por (posición, cláusula) y ordenadas por rendimiento.

    Se agrupa por lo que exige la tarifa y no por caso: la misma cláusula en
    veinte productos es una pregunta, no veinte. Primero la que más casos
    desatasca; a igualdad, por posición, para que el orden no baile entre una
    recarga y la siguiente.
    """
    casos: dict[tuple[str, str], dict[uuid.UUID, ClassificationDecision]] = defaultdict(dict)
    fichas: dict[tuple[str, str], dict[str, None]] = defaultdict(dict)
    textos: dict[tuple[str, str], str] = {}
    for decision in decisiones:
        for q in preguntas_de(decision):
            clave = (str(q["codigo"]), str(q["exige"]))
            casos[clave][decision.id] = decision
            if q.get("mercancia"):
                fichas[clave][str(q["mercancia"])] = None
            textos.setdefault(clave, str(q.get("texto") or ""))

    grupos = [
        PreguntaPendiente(
            codigo=codigo,
            exige=exige,
            texto=textos[(codigo, exige)],
            decisiones=tuple(casos[(codigo, exige)].values()),
            fichas=tuple(fichas[(codigo, exige)]),
        )
        for codigo, exige in casos
    ]
    grupos.sort(key=lambda g: (-len(g.decisiones), g.codigo, g.exige))
    return grupos


def preguntas_pendientes(session: Session) -> list[PreguntaPendiente]:
    """Las preguntas vivas sobre el conjunto ENTERO de pendientes, sin página."""
    return agrupar(session.scalars(pendientes_vigentes()).all())


def productos_que_preguntaban(session: Session, clausula: str) -> list[uuid.UUID]:
    """Los productos cuyo caso pendiente tiene esa cláusula delante.

    Va por la cláusula y NO por la posición: la respuesta se guarda por
    (término de la ficha, cláusula) y el motor la aplica a cualquier posición
    cuyo texto diga esa frase. Por eso puede recalcular casos de otra tarjeta
    con la misma cláusula, y es correcto: la respuesta es verdad ahí también.
    """
    afectados: list[uuid.UUID] = []
    vistos: set[uuid.UUID] = set()
    for decision in session.scalars(pendientes_vigentes()).all():
        if decision.product_id is None or decision.product_id in vistos:
            continue
        if any(q["exige"] == clausula for q in preguntas_de(decision)):
            vistos.add(decision.product_id)
            afectados.append(decision.product_id)
    return afectados


def productos_por_id(session: Session, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Product]:
    """Los productos de esos casos, en UNA consulta y no una por caso."""
    if not ids:
        return {}
    return {p.id: p for p in session.scalars(sa.select(Product).where(Product.id.in_(ids))).all()}
