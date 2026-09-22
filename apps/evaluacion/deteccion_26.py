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

SE CORRE SOLO

    python -m apps.evaluacion.deteccion_26 --escenarios
    python -m apps.evaluacion.deteccion_26 --escenario corpus-espejo

La métrica no vale si sólo la puede correr quien la escribió: el número deja de
ser verificable y pasa a ser una afirmación. Por eso el listado va primero —
elegir el escenario a ciegas ya costó un falso positivo que no existía.
"""

from __future__ import annotations

import argparse
import re
import uuid
from typing import TYPE_CHECKING, Final, NamedTuple

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
    SyntheticScenario,
)
from database.repositories.tariff import TariffCatalogRepository

from apps.evaluacion.hs_accuracy import SesionSoloLectura

if TYPE_CHECKING:
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


# ─────────────────────────────── LÍNEA DE COMANDOS ───────────────────────────


class Corpus(NamedTuple):
    """Un escenario, con lo que pesa. Para elegir sin adivinar el UUID."""

    id: uuid.UUID
    slug: str
    nombre: str
    pedimentos: int
    eventos: int


def corpus_disponibles(session: Session) -> list[Corpus]:
    """Qué hay para medir.

    Existe porque elegir escenario a ciegas ya costó un número equivocado: el
    id del sembrado y el del corpus se parecen, y medir el que no era produjo
    un falso positivo que no existía.
    """
    peds = (
        sa.select(
            Pedimento.synthetic_scenario_id.label("escenario"),
            sa.func.count().label("n"),
        )
        .group_by(Pedimento.synthetic_scenario_id)
        .subquery()
    )
    gts = (
        sa.select(
            GroundTruthRecord.synthetic_scenario_id.label("escenario"),
            sa.func.count().label("n"),
        )
        .group_by(GroundTruthRecord.synthetic_scenario_id)
        .subquery()
    )
    filas = session.execute(
        sa.select(
            SyntheticScenario.id,
            SyntheticScenario.slug,
            SyntheticScenario.name,
            sa.func.coalesce(peds.c.n, 0),
            sa.func.coalesce(gts.c.n, 0),
        )
        .outerjoin(peds, peds.c.escenario == SyntheticScenario.id)
        .outerjoin(gts, gts.c.escenario == SyntheticScenario.id)
        .order_by(sa.func.coalesce(peds.c.n, 0).desc())
    ).all()
    return [Corpus(*fila) for fila in filas]


def _resolver(session: Session, texto: str) -> Corpus:
    """Acepta slug o UUID. Si no existe, dice cuáles sí — no falla a secas."""
    disponibles = corpus_disponibles(session)
    try:
        buscado = uuid.UUID(texto)
    except ValueError:
        elegido = next((c for c in disponibles if c.slug == texto), None)
    else:
        elegido = next((c for c in disponibles if c.id == buscado), None)
    if elegido is None:
        catalogo = "\n".join(f"  {c.slug:<28} {c.pedimentos:>4} pedimentos" for c in disponibles)
        raise SystemExit(f"no hay escenario «{texto}». Los que hay:\n{catalogo}")
    return elegido


def _tabla(disponibles: list[Corpus]) -> str:
    lineas = [f"{'SLUG':<28} {'PEDIMENTOS':>10} {'EVENTOS':>8}  NOMBRE"]
    lineas += [f"{c.slug:<28} {c.pedimentos:>10} {c.eventos:>8}  {c.nombre}" for c in disponibles]
    lineas.append("")
    lineas.append("Los UUID también se aceptan en --escenario.")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--escenario",
        help=(
            "Slug o UUID del corpus a medir. SIN ÉL se mide toda la base, que "
            "mezcla corpus distintos en una sola población."
        ),
    )
    parser.add_argument(
        "--escenarios",
        action="store_true",
        help="Lista los corpus disponibles y termina. No mide nada.",
    )
    args = parser.parse_args(argv)

    from sqlalchemy.orm import Session as SesionSql

    from apps.api.config import get_settings

    motor = sa.create_engine(get_settings().sqlalchemy_url)
    try:
        sesion = SesionSql(motor)
    except sa.exc.OperationalError as error:  # pragma: no cover - depende del entorno
        raise SystemExit(f"la base no responde: {error.orig}") from error

    with sesion:
        try:
            disponibles = corpus_disponibles(sesion)
        except sa.exc.OperationalError as error:  # pragma: no cover - depende del entorno
            raise SystemExit(f"la base no responde: {error.orig}") from error
        if args.escenarios:
            print(_tabla(disponibles))
            sesion.rollback()
            return 0

        elegido = _resolver(sesion, args.escenario) if args.escenario else None
        ambito = (
            f"{elegido.slug} · {elegido.nombre} · {elegido.pedimentos} pedimentos"
            if elegido
            else f"TODA LA BASE · {len(disponibles)} escenarios mezclados en una población"
        )
        try:
            reporte = medir(sesion, escenario=elegido.id if elegido else None)
        finally:
            sesion.rollback()

    print(f"ÁMBITO  {ambito}")
    print("        sesión de sólo lectura y rollback al final: no se escribió nada")
    print()
    print(informe(reporte))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
