"""Corre la métrica de detección del §26 contra la base, sin escribir.

`core.evaluation.deteccion` no conoce la base: aquí se leen los eventos
sembrados, los hallazgos del motor y las partidas, y se le entregan.

EL SUBTIPO DEL NICO LO DECIDE EL CATÁLOGO, NO UNA LISTA A MANO

De los casos de NICO, unos los caza el catálogo —el declarado no existe en su
fracción— y otros exigen ficha técnica, porque el NICO existe y sólo está
equivocado. Cuál es cuál no se escribe a mano: se consulta la tarifa vigente
el día de la operación. Una lista fija de seis fracciones sería ajustar la
medición al corpus que tenemos hoy.

NO ESCRIBE NADA. Misma sesión de sólo lectura que el harness de hs_accuracy:
una evaluación que ensucie la base deja de medir lo que dice medir.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from core.evaluation.deteccion import (
    NICO_EXIGE_FICHA,
    NICO_LO_CAZA_EL_CATALOGO,
    Evento,
    Hallazgo,
    Reporte,
    evaluar,
)
from database.models import GroundTruthRecord, Pedimento, PedimentoItem, RiskFinding
from database.repositories.tariff import TariffCatalogRepository

from apps.evaluacion.hs_accuracy import SesionSoloLectura

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = structlog.stdlib.get_logger("apps.evaluacion.deteccion")


def _subtipo_nico(session: Session, partida: PedimentoItem, operacion: date | None) -> str:
    """¿Lo caza el catálogo, o exige ficha técnica?

    Si el NICO declarado NO está entre los vigentes de su fracción, el catálogo
    lo caza solo. Si está, el catálogo no puede decir nada más: que exista no
    significa que sea el que corresponde a la mercancía.
    """
    if not partida.declared_fraction_code or not partida.declared_nico_code:
        return NICO_EXIGE_FICHA
    if operacion is None:
        return NICO_EXIGE_FICHA
    vigentes = TariffCatalogRepository(session).nicos(
        on_date=operacion, fraction_code=partida.declared_fraction_code
    )
    if vigentes and partida.declared_nico_code not in vigentes:
        return NICO_LO_CAZA_EL_CATALOGO
    return NICO_EXIGE_FICHA


def recolectar(session: Session) -> tuple[list[Evento], list[Hallazgo], list[str]]:
    """Lee de la base lo que la métrica necesita. Nada más."""
    partidas = {fila.id: fila for fila in session.scalars(sa.select(PedimentoItem)).all()}
    fechas: dict[uuid.UUID, date] = {
        fila.id: fila.operation_date
        for fila in session.execute(sa.select(Pedimento.id, Pedimento.operation_date)).all()
    }

    eventos: list[Evento] = []
    for gt in session.scalars(sa.select(GroundTruthRecord)).all():
        if gt.pedimento_item_id is None:
            # Sin partida no se puede emparejar con ningún hallazgo. Se omite
            # y se nota: un evento que no apunta a nada no mide nada.
            log.warning("deteccion.evento_sin_partida", error_type=gt.error_type)
            continue
        partida = partidas.get(gt.pedimento_item_id)
        subtipo = None
        if gt.error_type == "WRONG_NICO" and partida is not None:
            subtipo = _subtipo_nico(session, partida, fechas.get(partida.pedimento_id))
        eventos.append(
            Evento(
                partida_id=str(gt.pedimento_item_id),
                error_type=gt.error_type,
                detectable=gt.expected_detection,
                subtipo=subtipo,
            )
        )

    hallazgos = [
        Hallazgo(partida_id=str(f.pedimento_item_id), finding_type=f.finding_type)
        for f in session.scalars(
            sa.select(RiskFinding).where(RiskFinding.pedimento_item_id.isnot(None))
        ).all()
    ]
    return eventos, hallazgos, [str(i) for i in partidas]


def medir(session: Session) -> Reporte:
    """La métrica, sobre una sesión que no puede escribir."""
    solo_lectura = SesionSoloLectura(session)
    eventos, hallazgos, partidas = recolectar(solo_lectura)  # type: ignore[arg-type]
    reporte = evaluar(eventos, hallazgos, partidas=partidas)
    log.info(
        "deteccion.medida",
        eventos=reporte.eventos_totales,
        medibles=reporte.eventos_medibles,
        tp=reporte.agregado.tp,
        fp=reporte.agregado.fp,
        fn=reporte.agregado.fn,
    )
    return reporte


def informe(r: Reporte) -> str:
    """El reporte, con sus tres límites escritos. Sin ellos el número engaña."""
    lineas = [
        f"EVENTOS  {r.eventos_totales} sembrados · {r.eventos_medibles} medibles",
        f"  indetectables por construcción: {r.excluidos_por_indetectables} (fuera del recall)",
    ]
    if r.excluidos_sin_detector:
        detalle = ", ".join(f"{k}={v}" for k, v in sorted(r.excluidos_sin_detector.items()))
        lineas.append(f"  sin detector construido todavía: {detalle}")

    a = r.agregado
    lineas += [
        "",
        f"AGREGADO  TP {a.tp} · FP {a.fp} · FN {a.fn} · TN {a.tn}",
        f"  precision {a.precision} · recall {a.recall} · F1 {a.f1}",
        f"  margen del recall al 95 %: ±{a.margen_95} puntos",
        "",
        f"FALSOS POSITIVOS  {a.fp} sobre {r.partidas_limpias} partidas limpias "
        f"({r.tasa_falsos_positivos} %)",
        f"  de ellos, revisión de origen: {r.falsos_positivos_de_revision}",
        f"  hallazgos fuera de su anomalía: {r.hallazgos_fuera_de_su_anomalia}",
        "",
        "POR TIPO",
    ]
    for tipo, c in sorted(r.por_tipo.items()):
        lineas.append(f"  {tipo:<28} TP {c.tp} FN {c.fn} · recall {c.recall} (±{c.margen_95})")
    return "\n".join(lineas)
