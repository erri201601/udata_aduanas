"""Corre la métrica de detección del §26 contra la base, sin escribir.

`core.evaluation.deteccion` no conoce la base: aquí se leen los eventos
sembrados, los hallazgos del motor y las partidas, y se le entregan.

LOS SUBTIPOS SALEN DEL DATO, NO DE UNA LISTA A MANO

El corpus colapsa cuatro anomalías distintas en WRONG_VALUE y las separa por
`expected_field`: valor en aduana, tasa de IGI, base de IVA e importe de IVA.
Sólo la primera tiene detector construido. Aquí se traducen a subtipos para
que el reporte no presente como una sola capacidad lo que son cuatro.

«NO PUDO» SE LEE DE LA REVISIÓN, NO SE SUPONE

Cuando el motor no logra sostener una clasificación, la revisión del Espejo lo
deja escrito en `unverifiable`: «línea N: la clasificación no llegó a ser
defendible». De ahí sale que un fallo de FRACCIÓN sea «el detector existe y no
pudo» en vez de «no cazó». Suponerlo habría sido escribir la excusa del motor
en la métrica que lo mide.

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

import re
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from core.evaluation.deteccion import (
    NICO_EXIGE_FICHA,
    NICO_LO_CAZA_EL_CATALOGO,
    SUBTIPO_POR_CAMPO,
    Evento,
    Hallazgo,
    Reporte,
    evaluar,
)
from database.models import (
    GroundTruthRecord,
    Pedimento,
    PedimentoItem,
    RiskFinding,
    ShadowReview,
)
from database.repositories.tariff import TariffCatalogRepository

from apps.evaluacion.hs_accuracy import SesionSoloLectura

if TYPE_CHECKING:
    import uuid
    from datetime import date

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


_SIN_CLASIFICACION: Final = "la clasificación no llegó a ser defendible"
_LINEA: Final = re.compile(r"^\s*línea\s+(\d+)\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)


def _lineas_sin_clasificacion(session: Session) -> set[uuid.UUID]:
    """Partidas cuya revisión dice que la clasificación no se sostuvo.

    Se mira la revisión MÁS RECIENTE de cada pedimento: una auditoría vieja no
    describe el estado de hoy.
    """
    ultima: dict[uuid.UUID, ShadowReview] = {}
    for revision in session.scalars(
        sa.select(ShadowReview).order_by(ShadowReview.created_at)
    ).all():
        ultima[revision.pedimento_id] = revision

    por_linea = {
        (fila.pedimento_id, fila.line_number): fila.id
        for fila in session.execute(
            sa.select(PedimentoItem.pedimento_id, PedimentoItem.line_number, PedimentoItem.id)
        ).all()
    }

    sin_clasificar: set[uuid.UUID] = set()
    for pedimento_id, revision in ultima.items():
        for motivo in revision.unverifiable or []:
            coincidencia = _LINEA.match(motivo)
            if coincidencia is None or _SIN_CLASIFICACION not in coincidencia.group(2):
                continue
            partida = por_linea.get((pedimento_id, int(coincidencia.group(1))))
            if partida is not None:
                sin_clasificar.add(partida)
    return sin_clasificar


def recolectar(
    session: Session, *, escenario: uuid.UUID | None = None
) -> tuple[list[Evento], list[Hallazgo], list[str]]:
    """Lee de la base lo que la métrica necesita. Nada más.

    `escenario` acota a un corpus, y acota LAS TRES COSAS: eventos, partidas y
    hallazgos. Acotar sólo los eventos dejaría las partidas de otro escenario
    contadas como limpias y sus hallazgos como falsos positivos — el número que
    más importa, estropeado por un artefacto de la consulta.
    """
    consulta_partidas = sa.select(PedimentoItem)
    consulta_pedimentos = sa.select(Pedimento.id, Pedimento.operation_date)
    if escenario is not None:
        del_escenario = sa.select(Pedimento.id).where(Pedimento.synthetic_scenario_id == escenario)
        consulta_partidas = consulta_partidas.where(PedimentoItem.pedimento_id.in_(del_escenario))
        consulta_pedimentos = consulta_pedimentos.where(
            Pedimento.synthetic_scenario_id == escenario
        )

    partidas = {fila.id: fila for fila in session.scalars(consulta_partidas).all()}
    fechas: dict[uuid.UUID, date] = {
        fila.id: fila.operation_date for fila in session.execute(consulta_pedimentos).all()
    }

    sin_clasificar = _lineas_sin_clasificacion(session)

    consulta = sa.select(GroundTruthRecord)
    if escenario is not None:
        consulta = consulta.where(GroundTruthRecord.synthetic_scenario_id == escenario)

    eventos: list[Evento] = []
    for gt in session.scalars(consulta).all():
        if gt.pedimento_item_id is None:
            # Sin partida no se puede emparejar con ningún hallazgo. Se omite
            # y se nota: un evento que no apunta a nada no mide nada.
            log.warning("deteccion.evento_sin_partida", error_type=gt.error_type)
            continue
        partida = partidas.get(gt.pedimento_item_id)
        subtipo = None
        if gt.error_type == "WRONG_NICO" and partida is not None:
            subtipo = _subtipo_nico(session, partida, fechas.get(partida.pedimento_id))
        elif gt.error_type == "WRONG_VALUE":
            subtipo = SUBTIPO_POR_CAMPO.get(gt.expected_field or "")
        eventos.append(
            Evento(
                partida_id=str(gt.pedimento_item_id),
                error_type=gt.error_type,
                detectable=gt.expected_detection,
                subtipo=subtipo,
                pudo_intentarlo=gt.pedimento_item_id not in sin_clasificar,
            )
        )

    # Sólo los hallazgos de las partidas del corpus: uno de otro escenario
    # entraría como falso positivo sin serlo.
    hallazgos = [
        Hallazgo(partida_id=str(f.pedimento_item_id), finding_type=f.finding_type)
        for f in session.scalars(
            sa.select(RiskFinding).where(RiskFinding.pedimento_item_id.isnot(None))
        ).all()
        if f.pedimento_item_id in partidas
    ]
    return eventos, hallazgos, [str(i) for i in partidas]


def medir(session: Session, *, escenario: uuid.UUID | None = None) -> Reporte:
    """La métrica, sobre una sesión que no puede escribir."""
    solo_lectura = SesionSoloLectura(session)
    eventos, hallazgos, partidas = recolectar(solo_lectura, escenario=escenario)  # type: ignore[arg-type]
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
        lineas.append("  SIN DETECTOR CONSTRUIDO (no es fallo del motor: es código que falta)")
        for tipo, n in sorted(r.excluidos_sin_detector.items()):
            lineas.append(f"    {tipo:<32} {n}")
    if r.fn_por_causa:
        lineas.append("  POR QUÉ NO SE DETECTÓ")
        for causa, n in sorted(r.fn_por_causa.items()):
            lineas.append(f"    {causa:<32} {n}")

    a = r.agregado
    lineas += [
        "",
        f"AGREGADO  TP {a.tp} · FP {a.fp} · FN {a.fn} · TN {a.tn}",
        f"  precision {a.precision} · recall {a.recall} · F1 {a.f1}",
        f"  margen del recall al 95 %: ±{a.margen_95} puntos",
        "",
        f"COBERTURA  {r.partidas_senaladas} de {r.partidas_con_anomalia} partidas sucias "
        f"quedaron señaladas por algo ({r.cobertura_por_partida} %)",
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
