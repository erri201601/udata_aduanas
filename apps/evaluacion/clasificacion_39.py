"""Mide la clasificación contra verdad conocida (§39).

POR QUÉ HACÍA FALTA OTRA MEDICIÓN

La detección ya se medía bien (`deteccion_26`): 55 anomalías sembradas, se
sabe cuáles son, y de ahí salen precisión y recall con su margen.

La clasificación no. `/metrics/classification` compara el motor con los
dictámenes humanos —trece casos— y hasta el 30-sep contaba como FALLO las
veces que el motor se abstuvo, lo que daba un 0.00 % que no significaba lo que
parecía.

Aquí se mide contra otra verdad, y es mucho mayor: **todas las partidas cuya
fracción declarada es correcta por construcción** — las limpias y también las
sucias cuya anomalía no toca la fracción. Ésa es la respuesta, y el motor no la
ve.

LAS TRES CIFRAS, Y NO SE MEZCLAN

    acertó      propuso fracción y es la correcta
    falló       propuso fracción y es otra
    se abstuvo  no propuso ninguna

La precisión se calcula SOBRE LO QUE CONTESTÓ. La cobertura, sobre el total.
Son dos preguntas distintas —«¿acierta cuando habla?» y «¿cuántas veces
habla?»— y un solo porcentaje las confunde. Un motor que contesta dos veces y
acierta las dos tiene 100 % de precisión y 1,6 % de cobertura, y decir sólo lo
primero sería presumir de nada.

NO SE MIDEN LAS QUE TIENEN LA FRACCIÓN MUTADA — Y SÓLO ÉSAS

Hasta el 5-oct se excluía cualquier partida con anomalía sembrada, sobre esta
premisa escrita aquí mismo: «una partida con anomalía sembrada tiene la
fracción declarada MAL a propósito».

**Es falsa.** De las siete clases de anomalía, sólo dos tocan la fracción:

    WRONG_FRACTION            7     SÍ la toca
    WRONG_NICO                6     SÍ
    WRONG_VALUE              24     no
    WRONG_UNIT                6     no
    INCONSISTENT_QUANTITY     6     no
    MISSING_TECHNICAL_FIELD   6     no
    WRONG_ORIGIN              6     no

En las otras cinco la fracción declarada sigue siendo correcta, y el motor se
podía contrastar contra ella desde el principio. Eran **42 partidas** sin
mirar: un tercio de lo medible, y `deteccion_26` no las cubría porque sólo
pregunta «¿señalamos la anomalía?», no «¿es absurda la fracción que propones?».

LO QUE EL PUNTO CIEGO TAPABA (César, 5-oct)

Lo encontró un clasificador revisando a mano, no la medición:

    PED_SIM_015-005  CABLE DE ACERO >=25.4 MM   motor 85442001, declarada 73121099
    PED_SIM_010-005  CABLE DE ACERO 12.7-25.4   motor 85442001, declarada 73121099

8544 son cables ELÉCTRICOS aislados y coaxiales. Las dos partidas llevan
sembrado un `MISSING_TECHNICAL_FIELD`, así que la vieja consulta las excluía —y
con ellas la respuesta más absurda que el motor había dado en todo el corpus.

Una métrica con un punto ciego es peor que no tenerla: da confianza sobre lo
que no mira. «Precisión 100 %» era cierto y significaba menos de lo que
parecía.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from core.classification import nico_de
from core.classification.nico_por_medida import medidas_de
from core.evaluation.intervalos import wilson
from database.repositories.tariff import TariffCatalogRepository

from apps.evaluacion.procedencia import linea_de_procedencia, procedencia

if TYPE_CHECKING:
    from core.classification import NicoCatalog


@dataclass
class Resultado:
    """Lo que salió, separado por lo que significa cada cosa."""

    acerto: int = 0
    fallo: int = 0
    se_abstuvo: int = 0
    sin_decision: int = 0
    """Partidas cuyo producto nunca se clasificó. No es una abstención del
    motor: es que nadie se lo pidió."""

    sin_fundamento: int = 0
    """Partidas cuyo último veredicto dice que con esta ficha no se puede
    determinar la fracción. No se miden: no hay verdad contra la que medir, y
    usar la declaración contradiría al clasificador que la acaba de poner en
    duda."""

    contra_dictamen: int = 0
    """Cuántas se midieron contra el dictamen de un clasificador."""
    contra_declaracion: int = 0
    """Cuántas se midieron contra la fracción declarada en el pedimento."""

    hs_acerto: int = 0
    """Contestó y los 6 primeros dígitos (la subpartida del SA) son los de la
    verdad (§39 «HS accuracy»): acierta el sistema armonizado aunque falle la
    apertura nacional."""
    hs_fallo: int = 0
    revision_humana: int = 0
    """De las medibles, cuántas mandó el motor a revisión humana (§39 «human
    review rate»)."""

    nico_acerto: int = 0
    """Fracción acertada y NICO entregado igual al de la verdad."""
    nico_fallo: int = 0
    nico_se_abstuvo: int = 0
    """Fracción acertada pero sin NICO: la fracción tiene varios y no se elige."""
    nico_sin_verdad: int = 0
    """Fracción acertada, pero ni el dictamen ni la declaración traen NICO."""
    errores_nico: list[tuple[str, str, str]] = field(default_factory=list)
    """(sku, NICO verdadero, NICO entregado)."""

    errores: list[tuple[str, str, str, str]] = field(default_factory=list)
    """(sku, verdad, propuesta, de dónde sale la verdad) de cada fallo. Sin
    esto no se puede aprender nada del número."""

    @property
    def contestadas(self) -> int:
        return self.acerto + self.fallo

    @property
    def medibles(self) -> int:
        return self.contestadas + self.se_abstuvo

    @property
    def precision(self) -> Decimal | None:
        """De lo que contestó, cuánto acertó. `None` si no contestó nada."""
        if not self.contestadas:
            return None
        return (Decimal(self.acerto) / Decimal(self.contestadas) * 100).quantize(Decimal("0.01"))

    @property
    def cobertura(self) -> Decimal | None:
        """De lo que pudo contestar, cuánto contestó."""
        if not self.medibles:
            return None
        return (Decimal(self.contestadas) / Decimal(self.medibles) * 100).quantize(Decimal("0.01"))

    @property
    def tasa_revision_humana(self) -> Decimal | None:
        if not self.medibles:
            return None
        return (Decimal(self.revision_humana) / Decimal(self.medibles) * 100).quantize(
            Decimal("0.01")
        )

    @property
    def nico_contestadas(self) -> int:
        return self.nico_acerto + self.nico_fallo

    @property
    def nico_medibles(self) -> int:
        return self.nico_contestadas + self.nico_se_abstuvo


_CON_FRACCION_FIABLE = sa.text(
    """
    SELECT p.sku,
           i.declared_fraction_code AS declarada,
           (
             SELECT d.fraction_code
             FROM intelligence.classification_decisions d
             WHERE d.product_id = i.product_id
               AND d.data_origin <> 'HUMAN_VALIDATED'
             ORDER BY d.created_at DESC
             LIMIT 1
           ) AS propuesta,
           (
             SELECT d.requires_human_review
             FROM intelligence.classification_decisions d
             WHERE d.product_id = i.product_id
               AND d.data_origin <> 'HUMAN_VALIDATED'
             ORDER BY d.created_at DESC
             LIMIT 1
           ) AS revision_humana,
           -- EL DICTAMEN HUMANO DE LA MISMA FICHA, SI LO HAY
           --
           -- Se empareja por `product_dna_id` y no por partida: el criterio de
           -- un clasificador es sobre la MERCANCÍA, y la misma ficha declarada
           -- en otro pedimento tiene la misma fracción correcta. Él mismo lo
           -- escribe así —una respuesta, varios SKU debajo— y es como ya
           -- empareja el resto del sistema.
           --
           -- MANDA EL ÚLTIMO VEREDICTO, LLEGUE O NO A UNA FRACCIÓN (6-oct)
           --
           -- Aquí se filtraba `fraction_code IS NOT NULL` ANTES de elegir el
           -- más reciente, y eso convertía un `FALTA_INFORMACION` en invisible:
           -- la consulta lo saltaba y volvía al dictamen anterior. Pasó con el
           -- cable PED_SIM_010-005. El 5-oct el clasificador dictaminó
           -- `73121099`; el 6-oct escribió «no tengo fundamento suficiente
           -- para elegir 73121005 ni 73121099», y esta medición seguía usando
           -- `73121099` como verdad. Una fracción que su autor retiró.
           --
           -- Se elige el último, y si no tiene fracción `sin_fundamento` lo
           -- dice: la ficha no tiene verdad contra la que medir.
           (
             SELECT h.fraction_code
             FROM intelligence.classification_decisions h
             WHERE h.product_dna_id = (
                     SELECT d2.product_dna_id
                     FROM intelligence.classification_decisions d2
                     WHERE d2.product_id = i.product_id
                     ORDER BY d2.created_at DESC LIMIT 1
                   )
               AND h.data_origin = 'HUMAN_VALIDATED'
             ORDER BY h.created_at DESC
             LIMIT 1
           ) AS dictamen,
           (
             SELECT h.nico_code
             FROM intelligence.classification_decisions h
             WHERE h.product_dna_id = (
                     SELECT d2.product_dna_id
                     FROM intelligence.classification_decisions d2
                     WHERE d2.product_id = i.product_id
                     ORDER BY d2.created_at DESC LIMIT 1
                   )
               AND h.data_origin = 'HUMAN_VALIDATED'
             ORDER BY h.created_at DESC
             LIMIT 1
           ) AS dictamen_nico,
           i.declared_nico_code AS declarada_nico,
           -- Las medidas que el clasificador ve: lo observado o extraído de la
           -- ficha vigente, igual que `medidas_de_la_ficha` (ADR 0016).
           (
             SELECT jsonb_object_agg(a.name, a.value)
             FROM intelligence.product_attributes a
             JOIN intelligence.product_dnas dn ON dn.id = a.product_dna_id
             WHERE dn.product_id = i.product_id AND dn.is_current
               AND a.status IN ('OBSERVED', 'EXTRACTED')
           ) AS atributos_solidos,
           ped.operation_date AS fecha,
           COALESCE((
             SELECT h.fraction_code IS NULL
             FROM intelligence.classification_decisions h
             WHERE h.product_dna_id = (
                     SELECT d2.product_dna_id
                     FROM intelligence.classification_decisions d2
                     WHERE d2.product_id = i.product_id
                     ORDER BY d2.created_at DESC LIMIT 1
                   )
               AND h.data_origin = 'HUMAN_VALIDATED'
             ORDER BY h.created_at DESC
             LIMIT 1
           ), FALSE) AS sin_fundamento,
           EXISTS (
             SELECT 1 FROM intelligence.classification_decisions d
             WHERE d.product_id = i.product_id AND d.data_origin <> 'HUMAN_VALIDATED'
           ) AS hubo_decision
    FROM operational.pedimento_items i
    JOIN operational.products p ON p.id = i.product_id
    JOIN operational.pedimentos ped ON ped.id = i.pedimento_id
    WHERE i.declared_fraction_code IS NOT NULL
      -- SÓLO LAS QUE TIENEN LA FRACCIÓN MUTADA, NO TODAS LAS SUCIAS
      --
      -- De las siete clases de anomalía sembrada, sólo dos tocan la fracción:
      --
      --     WRONG_FRACTION  7      SÍ toca la fracción
      --     WRONG_NICO      6      SÍ
      --     WRONG_VALUE    24      no
      --     WRONG_UNIT      6      no
      --     INCONSISTENT_QUANTITY 6  no
      --     MISSING_TECHNICAL_FIELD 6  no
      --     WRONG_ORIGIN    6      no
      --
      -- En las otras cinco la fracción declarada sigue siendo correcta por
      -- construcción, así que se puede contrastar igual que en una limpia.
      AND NOT EXISTS (
        SELECT 1 FROM intelligence.ground_truth_records g
        WHERE g.pedimento_item_id = i.id
          AND g.error_type IN ('WRONG_FRACTION', 'WRONG_NICO')
      )
    """
)


def medir(sesion: sa.orm.Session, nicos: NicoCatalog | None = None) -> Resultado:
    """Compara lo propuesto con la verdad, y la verdad no siempre es la declarada.

    EL DICTAMEN DE UN CLASIFICADOR MANDA SOBRE LA DECLARACIÓN

    Hasta hoy la verdad era siempre `declared_fraction_code`, y eso daba por
    bueno algo que el corpus no garantiza: la declaración de una partida
    «limpia» es la que el generador sintético escribió, no una fracción
    verificada por nadie.

    El 6 de octubre se vio en catorce partidas de golpe. Un clasificador
    contestó en la consola que un cable de construcción 6x36 no cumple
    «constituidos por 7 alambres», el motor pasó a resolver `73121005` —y la
    medición lo contó como CATORCE FALLOS, porque las catorce declaran
    `73121099`.

    Las cinco que están en su dictamen escrito dicen `73121005`, la misma que
    el motor. Las otras nueve son la misma mercancía. Es decir: el motor
    acertó, el corpus declaraba mal, y la métrica llamó error al acierto.

    Una métrica que contradice al único experto del sistema no mide la calidad
    del motor: mide el parecido con un dato sintético.

    Orden de precedencia, y es el del §39:

        1. el dictamen humano de esa ficha, si existe
        2. la fracción declarada, cuando es fiable

    El informe dice cuántas se midieron contra cada cosa. Sin eso, el
    porcentaje no se puede interpretar: 100 % contra declaración sintética y
    100 % contra dictamen humano son dos afirmaciones muy distintas.

    EL NICO (§19, §39), SÓLO DONDE LA FRACCIÓN ACERTÓ

    Medir el NICO de una fracción equivocada mezclaría dos errores en uno. El
    NICO que se compara es el que entrega `nico_de` para la fracción
    propuesta: es una función determinista de la fracción y la fecha, la misma
    que usa el clasificador, así que no hace falta reclasificar el corpus para
    medirla. La verdad sigue la misma precedencia: el NICO del dictamen, y si
    no, el declarado (las partidas con `WRONG_NICO` ya están excluidas).
    """
    if nicos is None:
        nicos = TariffCatalogRepository(sesion)
    salida = Resultado()
    for fila in sesion.execute(_CON_FRACCION_FIABLE).all():
        if fila.sin_fundamento:
            salida.sin_fundamento += 1
            continue
        if not fila.hubo_decision:
            salida.sin_decision += 1
            continue
        if getattr(fila, "revision_humana", False):
            salida.revision_humana += 1
        if fila.propuesta is None:
            salida.se_abstuvo += 1
            continue

        if fila.dictamen is not None:
            verdad, de_donde = fila.dictamen, "dictamen"
            salida.contra_dictamen += 1
        else:
            verdad, de_donde = fila.declarada, "declaración"
            salida.contra_declaracion += 1

        if fila.propuesta[:6] == verdad[:6]:
            salida.hs_acerto += 1
        else:
            salida.hs_fallo += 1

        if fila.propuesta == verdad:
            salida.acerto += 1
            _medir_nico(salida, fila, nicos)
        else:
            salida.fallo += 1
            salida.errores.append((fila.sku, verdad, fila.propuesta, de_donde))
    return salida


def _medir_nico(salida: Resultado, fila: Any, nicos: NicoCatalog) -> None:
    verdad = fila.dictamen_nico if fila.dictamen is not None else None
    verdad = verdad or fila.declarada_nico
    if not verdad:
        salida.nico_sin_verdad += 1
        return
    atributos = getattr(fila, "atributos_solidos", None) or {}
    entregado, _ = nico_de(
        nicos,
        on_date=fila.fecha,
        fraction_code=fila.propuesta,
        medidas=medidas_de(list(atributos.items())),
    )
    if entregado is None:
        salida.nico_se_abstuvo += 1
    elif entregado == verdad:
        salida.nico_acerto += 1
    else:
        salida.nico_fallo += 1
        salida.errores_nico.append((fila.sku, verdad, entregado))


def informe(r: Resultado) -> str:
    """El informe, con los límites declarados antes que los números."""
    lineas = [
        linea_de_procedencia(procedencia()),
        "ÁMBITO  las partidas cuya fracción declarada es FIABLE: las limpias y",
        "        las sucias cuya anomalía sembrada NO toca la fracción. Sólo se",
        "        excluyen las de WRONG_FRACTION y WRONG_NICO, que son 13.",
        "",
        "VERDAD  manda el dictamen de un clasificador sobre la declaración. Una",
        "        declaración «limpia» la escribió el generador sintético; un",
        f"        dictamen lo firmó una persona.  contra dictamen: {r.contra_dictamen}"
        f" · contra declaración: {r.contra_declaracion}",
        "",
        f"MEDIBLES  {r.medibles} partidas con decisión del motor",
        f"  sin clasificar nunca: {r.sin_decision} (no cuentan: nadie se lo pidió)",
        f"  sin fundamento: {r.sin_fundamento} (un clasificador dijo que con esa ficha"
        " no se puede determinar)",
        "",
        f"CONTESTÓ  {r.contestadas} de {r.medibles}",
        f"  acertó  {r.acerto}",
        f"  falló   {r.fallo}",
        f"SE ABSTUVO  {r.se_abstuvo} — §8.2 funcionando, no es un error",
        "",
    ]
    if r.precision is not None:
        margen = wilson(r.acerto, r.contestadas)
        lineas.append(f"PRECISIÓN  {r.precision} % sobre lo que contestó")
        lineas.append(f"  margen al 95 %: ±{margen:.2f} puntos")
    else:
        lineas.append("PRECISIÓN  desconocida: no contestó ni una vez")

    if r.cobertura is not None:
        lineas.append(f"COBERTURA  {r.cobertura} % — cuántas veces se atrevió a contestar")
    if r.contestadas:
        lineas.append(
            f"HS (6 dígitos)  {Decimal(r.hs_acerto * 100) / r.contestadas:.2f} % "
            f"({r.hs_acerto} de {r.contestadas}) · margen al 95 %: "
            f"±{wilson(r.hs_acerto, r.contestadas):.2f} puntos"
        )
    if r.tasa_revision_humana is not None:
        lineas.append(
            f"REVISIÓN HUMANA  {r.tasa_revision_humana} % de las medibles "
            f"({r.revision_humana} de {r.medibles}) quedaron para una persona"
        )
        lineas.append(
            "  (una abstención por INSUFFICIENT_INFORMATION pide un dato al importador,"
            " no un revisor: no cuenta aquí)"
        )

    lineas += [
        "",
        "NICO  sólo donde la fracción acertó; se entrega con un único NICO o por medidas (ADR 0016)",
        f"  contestó {r.nico_contestadas} de {r.nico_medibles}: acertó {r.nico_acerto},"
        f" falló {r.nico_fallo}, se abstuvo {r.nico_se_abstuvo} (varios NICO sin regla)",
        f"  sin NICO de verdad contra el que medir: {r.nico_sin_verdad}",
    ]
    if r.nico_contestadas:
        lineas.append(
            f"  PRECISIÓN NICO  {Decimal(r.nico_acerto * 100) / r.nico_contestadas:.2f} %"
            f" · margen al 95 %: ±{wilson(r.nico_acerto, r.nico_contestadas):.2f} puntos"
        )
    for sku, verdad, entregado in r.errores_nico[:10]:
        lineas.append(f"  {sku:<18} NICO verdadero {verdad}  entregó {entregado}")

    if r.errores:
        lineas.append("")
        lineas.append("DÓNDE FALLÓ  (sin esto el porcentaje no enseña nada)")
        for sku, verdad, propuesta, de_donde in r.errores[:10]:
            lineas.append(f"  {sku:<18} {de_donde} dice {verdad}  propuso {propuesta}")
    return "\n".join(lineas)


def reclasificar(sesion: sa.orm.Session) -> int:
    """Vuelve a clasificar cada partida con el código ACTUAL, sin confirmar nada.

    POR QUÉ HACE FALTA (21-oct)

    `medir` lee las decisiones GUARDADAS, así que mide el motor que corrió la
    última vez, no el que hay en el árbol. Para saber si un cambio en la
    búsqueda mejora o empeora hay que reclasificar, y hasta hoy eso era un
    script suelto en cada intento (ADR 0007, ADR 0025).

    Pasa por `clasificar_borrador` y `save_classification`, el mismo camino
    que `POST /products/{id}/classify`. Las decisiones nuevas quedan en la
    transacción de quien llama, que es quien tiene que revertirla: `main` lo
    hace siempre.
    """
    from database.models import Pedimento, PedimentoItem
    from database.repositories.classification import save_classification

    from apps.api.clasificacion import clasificar_borrador
    from apps.api.dna import cargar_borrador, version_vigente

    filas = sesion.execute(
        sa.select(PedimentoItem.product_id, Pedimento.operation_date)
        .join(Pedimento, Pedimento.id == PedimentoItem.pedimento_id)
        .where(PedimentoItem.product_id.isnot(None))
    ).all()
    hechas = 0
    for producto, fecha in filas:
        if producto is None:  # el WHERE ya lo excluye; esto se lo dice a mypy
            continue
        ficha = version_vigente(sesion, producto)
        borrador = cargar_borrador(sesion, producto)
        if ficha is None or borrador is None:
            continue
        resultado = clasificar_borrador(
            sesion, borrador, operation_date=fecha, trade_flow="IMPORT"
        ).outcome
        save_classification(
            sesion, resultado, product_id=producto, product_dna_id=ficha.id, trade_flow="IMPORT"
        )
        hechas += 1
    sesion.flush()
    return hechas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target",
        default="local",
        choices=["local", "shared"],
        help="Qué Postgres se mide. 'shared' es la base del equipo.",
    )
    parser.add_argument(
        "--reclasificar",
        action="store_true",
        help=(
            "Reclasifica cada partida con el código actual antes de medir, dentro "
            "de una transacción que se revierte. Unos 5 minutos."
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
    sesion = SesionSql(motor)
    try:
        # Sólo lectura: esta medición no escribe nada, y el rollback lo
        # garantiza aunque alguien añada un INSERT por descuido.
        if args.reclasificar:
            print(
                f"RECLASIFICADO  {reclasificar(sesion)} partidas con el código actual (se revierte)"
            )
        print(informe(medir(sesion)))
    finally:
        sesion.rollback()
        sesion.close()
        motor.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
