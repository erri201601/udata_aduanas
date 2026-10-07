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
    python -m apps.evaluacion.deteccion_26 --escenario corpus_espejo_v1

Desde otra máquina, la base del equipo se alcanza con `--target shared`, que
lee `ADUANERO_SHARED_URL`. Desde la laptop de Persona 1 NO: ahí la base del
equipo es la local, y `shared` falla pidiendo una variable que no existe.

La métrica no vale si sólo la puede correr quien la escribió: el número deja de
ser verificable y pasa a ser una afirmación. Por eso el listado va primero —
elegir el escenario a ciegas ya costó un falso positivo que no existía.
"""

from __future__ import annotations

import argparse
import re
import uuid
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import sqlalchemy as sa
import structlog
from core.evaluation.deteccion import (
    DETECTOR_POR_ERROR,
    NICO_EXIGE_FICHA,
    NICO_LO_CAZA_EL_CATALOGO,
    SUBTIPO_POR_CAMPO,
    Evento,
    Hallazgo,
    Reporte,
    evaluar,
)
from database.models import (
    ClassificationDecision,
    GroundTruthRecord,
    Pedimento,
    PedimentoItem,
    ProductDna,
    RiskFinding,
    ShadowReview,
    SyntheticScenario,
)
from database.repositories.compensatory_duties import cuotas_vigentes
from database.repositories.findings import de_la_ultima_revision
from database.repositories.tariff import TariffCatalogRepository

from apps.evaluacion.hs_accuracy import SesionSoloLectura
from apps.evaluacion.procedencia import linea_de_procedencia, procedencia

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from sqlalchemy.orm import Session

log = structlog.stdlib.get_logger("apps.evaluacion.deteccion")

#: El hallazgo que emite el detector de ficha incompleta. Se toma del mapeo del
#: §26 en vez de reescribir la cadena: si allí cambia, aquí no se desincroniza.
DETECTOR_DE_FICHA: Final = DETECTOR_POR_ERROR["MISSING_TECHNICAL_FIELD"]
DETECTOR_DE_FRACCION: Final = DETECTOR_POR_ERROR["WRONG_FRACTION"]


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


def _fichas_recortadas_a_proposito(
    session: Session, partidas: Mapping[uuid.UUID, PedimentoItem], sembradas: set[uuid.UUID]
) -> set[tuple[str, str]]:
    """Pares (partida, MISSING_TECHNICAL_FIELD) que no se cuentan como FP.

    El corpus recorta la ficha de 21 partidas para que su clasificación no sea
    evaluable, y siembra el evento en sólo 6. En las otras 15 el detector
    acierta —la ficha está recortada— pero nadie pidió ese hallazgo. Ni acierto
    ni error: cierto y no contado.

    Se lee de la ficha VIGENTE, no de una lista escrita aquí: el día que el
    corpus recorte otras partidas, esto las sigue sin que nadie lo actualice.
    """
    # Un producto puede tocar VARIAS partidas, y un dict las colapsaría dejando
    # sólo la última: las demás perderían la exclusión y volverían a contarse
    # como falsos positivos por un hallazgo cierto. Hoy el corpus da un Product
    # por partida, pero eso ya se rompió una vez (PR #101, revertido en #103) y
    # la métrica no debería depender de que no vuelva a romperse.
    productos: dict[uuid.UUID, list[uuid.UUID]] = {}
    for pid, partida in partidas.items():
        if partida.product_id is not None:
            productos.setdefault(partida.product_id, []).append(pid)
    if not productos:
        return set()

    con_faltantes = session.execute(
        sa.select(ProductDna.product_id)
        .where(ProductDna.product_id.in_(productos))
        .where(ProductDna.is_current.is_(True))
        .where(sa.func.cardinality(ProductDna.missing_information) > 0)
    )
    return {
        (str(pid), DETECTOR_DE_FICHA)
        for fila in con_faltantes
        for pid in productos[fila.product_id]
        if pid not in sembradas
    }


def _fracciones_que_un_dictamen_contradice(
    session: Session, partidas: Mapping[uuid.UUID, PedimentoItem], sembradas: set[uuid.UUID]
) -> set[tuple[str, str]]:
    """Pares (partida, FRACTION_MISMATCH) que no se cuentan como falso positivo.

    UNA PARTIDA NO ES LIMPIA PORQUE EL CORPUS NO LE SEMBRARA NADA

    «Limpia» se definía como «sin evento sembrado», y eso daba por verificada
    una fracción que escribió el generador sintético. Cuando el motor señala
    que esa declaración está mal, la métrica lo contaba como falso positivo.

    Pasó el 6 de octubre, y fueron diez de golpe. Un clasificador contestó en
    la consola que un cable de construcción 6x36 no cumple «constituidos por 7
    alambres»; el motor pasó a proponer `73121005` donde el corpus declara
    `73121099`, y el Espejo levantó diez FRACTION_MISMATCH. Cuatro de esas diez
    tienen el veredicto firmado de ese mismo clasificador diciendo `73121005`.

    Es decir: el Espejo acertó. Señaló una declaración equivocada, que es
    exactamente su trabajo, y la métrica lo llamó error.

    NI ACIERTO NI ERROR: CIERTO Y NO CONTADO

    No entra como acierto porque nadie lo sembró —no hay evento que medir— y
    no entra como falso positivo porque es verdad. Es el mismo trato que las
    fichas recortadas a propósito, y por la misma razón.

    Se lee del veredicto humano VIGENTE y se empareja por `product_dna_id`: el
    criterio de un clasificador es sobre la MERCANCÍA, así que vale para la
    misma ficha declarada en otro pedimento. El día que llegue otro dictamen,
    esto lo sigue sin que nadie lo actualice.
    """
    con_producto = {
        pid: partida.product_id
        for pid, partida in partidas.items()
        if partida.product_id is not None and partida.declared_fraction_code is not None
    }
    if not con_producto:
        return set()

    # La ficha vigente de cada producto, y el ÚLTIMO veredicto humano de esa
    # ficha, llegue o no a una fracción.
    #
    # Antes se filtraba `fraction_code IS NOT NULL` aquí, y un
    # `FALTA_INFORMACION` posterior no retiraba el dictamen anterior: la
    # consulta lo saltaba. Si el último veredicto no tiene fracción, nadie
    # respalda ya que la declaración esté mal, y el hallazgo vuelve a contar.
    dictamen = sa.select(
        ClassificationDecision.product_dna_id,
        ClassificationDecision.fraction_code,
        ClassificationDecision.created_at,
    ).where(ClassificationDecision.data_origin == "HUMAN_VALIDATED")
    por_ficha: dict[uuid.UUID, tuple[Any, str | None]] = {}
    for dna_id, fraccion, cuando in session.execute(dictamen).all():
        if dna_id is None:
            continue
        previo = por_ficha.get(dna_id)
        if previo is None or cuando > previo[0]:
            por_ficha[dna_id] = (cuando, fraccion)

    ficha_de: dict[uuid.UUID, uuid.UUID] = {
        fila.product_id: fila.id
        for fila in session.execute(
            sa.select(ProductDna.product_id, ProductDna.id)
            .where(ProductDna.product_id.in_(set(con_producto.values())))
            .where(ProductDna.is_current.is_(True))
        ).all()
    }

    contradichas: set[tuple[str, str]] = set()
    for pid, product_id in con_producto.items():
        if pid in sembradas:
            # El corpus ya la sembró: su hallazgo es un acierto, no un
            # «cierto y no contado».
            continue
        dna_id = ficha_de.get(product_id)
        firmado = por_ficha.get(dna_id) if dna_id is not None else None
        if firmado is None or firmado[1] is None:
            continue
        if firmado[1] != partidas[pid].declared_fraction_code:
            contradichas.add((str(pid), DETECTOR_DE_FRACCION))
    return contradichas


#: El hallazgo del comparador de cuotas compensatorias (ADR 0009). No sale de
#: `DETECTOR_POR_ERROR` porque el corpus nunca lo modela como evento posible
#: (ningún pedimento sintético declara `cc_amount`) -- no hay "WRONG_X" del
#: que traducir.
DETECTOR_DE_CUOTA_COMPENSATORIA: Final = "COMPENSATORY_DUTY_MISMATCH"


def _cuotas_compensatorias_ciertas(
    session: Session,
    partidas: Mapping[uuid.UUID, PedimentoItem],
    fechas: Mapping[uuid.UUID, date],
) -> set[tuple[str, str]]:
    """Pares (partida, COMPENSATORY_DUTY_MISMATCH) que no se cuentan como
    falso positivo.

    Mismo criterio que `_fichas_recortadas_a_proposito`/
    `_fracciones_que_un_dictamen_contradice`: el corpus sintético nunca
    siembra una cuota compensatoria como evento posible (no existe
    "WRONG_COMPENSATORY_DUTY" en el generador), así que las 10 partidas de
    cable de acero de China que SÍ tienen una cuota real vigente (ADR 0009,
    `regulatory.compensatory_duties`) y venían limpias contarían como 10
    falsos positivos -- igual que pasó con FRACTION_MISMATCH en el #200,
    por la misma razón: un hallazgo cierto no es un error del motor.

    Se lee de `CompensatoryDuty` VIGENTE, no de una lista de partidas
    escrita a mano: si se carga otra cuota real, esto la sigue sin que
    nadie lo actualice.
    """
    ciertas: set[tuple[str, str]] = set()
    for pid, partida in partidas.items():
        if partida.country_of_origin is None or not partida.declared_fraction_code:
            continue
        fecha = fechas.get(partida.pedimento_id)
        if fecha is None:
            continue
        if cuotas_vigentes(
            session,
            on_date=fecha,
            origin_country=partida.country_of_origin,
            fraction_code=partida.declared_fraction_code,
        ):
            ciertas.add((str(pid), DETECTOR_DE_CUOTA_COMPENSATORIA))
    return ciertas


def consulta_de_hallazgos() -> sa.Select[Any]:
    """Los hallazgos que representan al motor de HOY.

    El tipo del retorno va sin parametrizar a propósito. `select(Modelo)` se
    anota `Select[tuple[Modelo]]` en unas versiones de SQLAlchemy y
    `Select[Modelo]` en otras, y `pyproject` pide `sqlalchemy>=2.0.36` sin
    tope: la local resuelve 2.0.52 y el CI instala la más nueva que haya ese
    día. Con la firma exacta, mypy pasaba aquí y fallaba allí — y el tipo
    concreto no aporta nada a quien lee esta función.

    Separada para poder probarla sin base: CI no tiene Postgres, así que lo
    que se comprueba allí es que la consulta LLEVE el acotamiento. Que el
    acotamiento haga lo que dice se comprobó contra la compartida — 302
    hallazgos del corpus en todas las revisiones, 86 en la vigente.
    """
    return sa.select(RiskFinding).where(
        RiskFinding.pedimento_item_id.isnot(None), de_la_ultima_revision()
    )


def recolectar(
    session: Session, *, escenario: uuid.UUID | None = None
) -> tuple[list[Evento], list[Hallazgo], list[str], set[tuple[str, str]]]:
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
    #
    # Y SÓLO LOS DE LA REVISIÓN VIGENTE. Cada pedimento se ha auditado varias
    # veces, y sin filtrar se mide la UNIÓN de todas las corridas en vez del
    # motor de hoy: un tipo que una auditoría vieja emitió y la actual ya no,
    # seguiría contando como acierto. La deduplicación del #112 no alcanza —
    # colapsa copias del mismo par (partida, tipo), no distingue de qué corrida
    # salió cada una. Ayer esto tapó un error durante horas (Persona 1, 23-sep).
    hallazgos = [
        Hallazgo(partida_id=str(f.pedimento_item_id), finding_type=f.finding_type)
        for f in session.scalars(consulta_de_hallazgos()).all()
        if f.pedimento_item_id in partidas
    ]
    sembradas = {
        e.pedimento_item_id
        for e in session.scalars(consulta).all()
        if e.error_type == "MISSING_TECHNICAL_FIELD" and e.pedimento_item_id is not None
    }
    recortadas = _fichas_recortadas_a_proposito(session, partidas, sembradas)

    sembradas_de_fraccion = {
        e.pedimento_item_id
        for e in session.scalars(consulta).all()
        if e.error_type == "WRONG_FRACTION" and e.pedimento_item_id is not None
    }
    contradichas = _fracciones_que_un_dictamen_contradice(session, partidas, sembradas_de_fraccion)
    cuotas_ciertas = _cuotas_compensatorias_ciertas(session, partidas, fechas)
    return (
        eventos,
        hallazgos,
        [str(i) for i in partidas],
        recortadas | contradichas | cuotas_ciertas,
    )


def medir(session: Session, *, escenario: uuid.UUID | None = None) -> Reporte:
    """La métrica, sobre una sesión que no puede escribir."""
    solo_lectura = SesionSoloLectura(session)
    eventos, hallazgos, partidas, recortadas = recolectar(solo_lectura, escenario=escenario)  # type: ignore[arg-type]
    reporte = evaluar(eventos, hallazgos, partidas=partidas, condiciones_sembradas=recortadas)
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
        f"  ciertos y no contados (ficha recortada, declaración que un dictamen "
        f"contradice, o cuota compensatoria real sobre partida limpia): "
        f"{r.condiciones_sembradas_no_contadas}",
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
    parser.add_argument(
        "--target",
        default="local",
        choices=["local", "shared"],
        help=(
            "Qué Postgres se mide. 'shared' es la base del equipo, en la laptop "
            "de Persona 1, y lee ADUANERO_SHARED_URL. DESDE ESA LAPTOP usa "
            "'local': ahí la base del equipo ES la local."
        ),
    )
    args = parser.parse_args(argv)

    from sqlalchemy.orm import Session as SesionSql

    from apps.api.config import UrlCompartidaAusenteError, url_de_postgres

    try:
        url = url_de_postgres(args.target)
    except UrlCompartidaAusenteError as error:
        raise SystemExit(str(error)) from error

    motor = sa.create_engine(url)
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

    print(linea_de_procedencia(procedencia()))
    print(f"ÁMBITO  {ambito}")
    print(f"        base: {args.target}" + ("  (la del equipo)" if args.target == "shared" else ""))
    print("        sesión de sólo lectura y rollback al final: no se escribió nada")
    print()
    print(informe(reporte))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
