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

import sqlalchemy as sa
from core.evaluation.intervalos import wilson

from apps.evaluacion.procedencia import linea_de_procedencia, procedencia


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


def medir(sesion: sa.orm.Session) -> Resultado:
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
    """
    salida = Resultado()
    for fila in sesion.execute(_CON_FRACCION_FIABLE).all():
        if fila.sin_fundamento:
            salida.sin_fundamento += 1
            continue
        if not fila.hubo_decision:
            salida.sin_decision += 1
            continue
        if fila.propuesta is None:
            salida.se_abstuvo += 1
            continue

        if fila.dictamen is not None:
            verdad, de_donde = fila.dictamen, "dictamen"
            salida.contra_dictamen += 1
        else:
            verdad, de_donde = fila.declarada, "declaración"
            salida.contra_declaracion += 1

        if fila.propuesta == verdad:
            salida.acerto += 1
        else:
            salida.fallo += 1
            salida.errores.append((fila.sku, verdad, fila.propuesta, de_donde))
    return salida


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

    if r.errores:
        lineas.append("")
        lineas.append("DÓNDE FALLÓ  (sin esto el porcentaje no enseña nada)")
        for sku, verdad, propuesta, de_donde in r.errores[:10]:
            lineas.append(f"  {sku:<18} {de_donde} dice {verdad}  propuso {propuesta}")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target",
        default="local",
        choices=["local", "shared"],
        help="Qué Postgres se mide. 'shared' es la base del equipo.",
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
        print(informe(medir(sesion)))
    finally:
        sesion.rollback()
        sesion.close()
        motor.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
