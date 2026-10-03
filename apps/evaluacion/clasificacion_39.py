"""Mide la clasificación contra verdad conocida (§39).

POR QUÉ HACÍA FALTA OTRA MEDICIÓN

La detección ya se medía bien (`deteccion_26`): 55 anomalías sembradas, se
sabe cuáles son, y de ahí salen precisión y recall con su margen.

La clasificación no. `/metrics/classification` compara el motor con los
dictámenes humanos —trece casos— y hasta el 30-sep contaba como FALLO las
veces que el motor se abstuvo, lo que daba un 0.00 % que no significaba lo que
parecía.

Aquí se mide contra otra verdad, y es mucho mayor: **las 126 partidas limpias
del corpus**. Una partida sin anomalía sembrada tiene su fracción declarada
correcta por construcción — ésa es la respuesta, y el motor no la ve.

LAS TRES CIFRAS, Y NO SE MEZCLAN

    acertó      propuso fracción y es la correcta
    falló       propuso fracción y es otra
    se abstuvo  no propuso ninguna

La precisión se calcula SOBRE LO QUE CONTESTÓ. La cobertura, sobre el total.
Son dos preguntas distintas —«¿acierta cuando habla?» y «¿cuántas veces
habla?»— y un solo porcentaje las confunde. Un motor que contesta dos veces y
acierta las dos tiene 100 % de precisión y 1,6 % de cobertura, y decir sólo lo
primero sería presumir de nada.

NO SE MIDEN LAS PARTIDAS SUCIAS

Una partida con anomalía sembrada tiene la fracción declarada MAL a propósito.
Compararse contra ella mediría al revés. De ésas se ocupa `deteccion_26`.
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

    errores: list[tuple[str, str, str]] = field(default_factory=list)
    """(sku, declarada, propuesta) de cada fallo. Sin esto no se puede
    aprender nada del número."""

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


_LIMPIAS = sa.text(
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
           EXISTS (
             SELECT 1 FROM intelligence.classification_decisions d
             WHERE d.product_id = i.product_id AND d.data_origin <> 'HUMAN_VALIDATED'
           ) AS hubo_decision
    FROM operational.pedimento_items i
    JOIN operational.products p ON p.id = i.product_id
    WHERE i.declared_fraction_code IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM intelligence.ground_truth_records g
        WHERE g.pedimento_item_id = i.id
      )
    """
)


def medir(sesion: sa.orm.Session) -> Resultado:
    """Compara lo propuesto con lo declarado, en las partidas limpias."""
    salida = Resultado()
    for fila in sesion.execute(_LIMPIAS).all():
        if not fila.hubo_decision:
            salida.sin_decision += 1
        elif fila.propuesta is None:
            salida.se_abstuvo += 1
        elif fila.propuesta == fila.declarada:
            salida.acerto += 1
        else:
            salida.fallo += 1
            salida.errores.append((fila.sku, fila.declarada, fila.propuesta))
    return salida


def informe(r: Resultado) -> str:
    """El informe, con los límites declarados antes que los números."""
    lineas = [
        linea_de_procedencia(procedencia()),
        "ÁMBITO  las 126 partidas LIMPIAS del corpus — su fracción declarada es",
        "        correcta por construcción. Las sucias se miden en deteccion_26.",
        "",
        f"MEDIBLES  {r.medibles} partidas con decisión del motor",
        f"  sin clasificar nunca: {r.sin_decision} (no cuentan: nadie se lo pidió)",
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
        for sku, declarada, propuesta in r.errores[:10]:
            lineas.append(f"  {sku:<18} declarada {declarada}  propuso {propuesta}")
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
