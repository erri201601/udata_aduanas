"""Valida un corpus de pedimentos sintéticos ANTES de cargarlo.

Un corpus con ground truth es una vara de medir, y una vara torcida es peor
que no medir: da un número y la confianza de haberlo medido. El ejemplo de
partida lo dejó claro — un juego anterior traía 10 de 12 tasas de IGI que no
existían en la tarifa, un NICO `00` inexistente en 8 de 9 fracciones y una
base de IVA sin DTA. Medir contra eso habría medido el corpus, no el motor.

QUÉ COMPRUEBA, Y POR QUÉ CADA COSA

Contra la tarifa y los catálogos reales, sobre lo ESPERADO:
  1. la fracción existe y está vigente
  2. el NICO existe dentro de esa fracción
  3. la tasa de IGI es la que dice la tarifa
  4. la UMC es una clave del Anexo 22
  5. la aritmética cuadra: valor en aduana, DTA, IGI, base de IVA e IVA

Sobre la coherencia interna del propio ground truth:
  6. ninguna partida declarada limpia difiere de lo esperado
  7. ninguna anomalía declarada deja de producir una diferencia
  8. el encabezado de cada pedimento cuadra con la suma de sus partidas

Las dos del medio son las que nadie escribe y las que más importan. Una
partida «limpia» contaminada mete un falso positivo que el motor no puede
evitar. Una anomalía que no altera nada mete un falso negativo imposible de
detectar. Las dos ensucian la métrica en direcciones opuestas y ninguna se
ve leyendo el documento.

LO QUE NO COMPRUEBA

No juzga si la fracción esperada es la correcta para esa mercancía: eso es
clasificar, y quien clasifica es el motor. Aquí sólo se comprueba que el
corpus sea coherente consigo mismo y con la tarifa vigente.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlalchemy.orm import Session

#: El corpus redondea a centavos; comparar con igualdad exacta produciría
#: fallos que no son errores del corpus sino del último decimal.
TOLERANCIA = Decimal("0.02")

#: Derecho de Trámite Aduanero, «8 al millar» (LFD art. 49). Mismo valor que
#: `core.taxation`; se repite aquí a propósito, porque este módulo valida un
#: corpus externo y no debe heredar en silencio lo que el motor asume.
TASA_DTA = Decimal("0.008")
TASA_IVA = Decimal("0.16")


def _d(valor: object) -> Decimal:
    return Decimal(str(valor))


@dataclass(frozen=True)
class Catalogo:
    """Lo que la base dice hoy, ya leído: la vara contra la que se compara."""

    igi_por_fraccion: Mapping[str, Decimal]
    nicos: frozenset[tuple[str, str]]
    unidades: frozenset[str]


@dataclass(frozen=True)
class Hallazgo:
    """Un defecto del corpus, con dónde está y qué es."""

    comprobacion: str
    donde: str
    detalle: str


def catalogo_desde(session: Session) -> Catalogo:
    """Lee tarifa, NICO y unidades vigentes. Sólo lectura."""
    session.execute(sa.text("SET TRANSACTION READ ONLY"))
    igi = {
        fila.code: fila.igi_rate
        for fila in session.execute(
            sa.text("select code, igi_rate from regulatory.tariff_fractions where valid_to is null")
        )
    }
    nicos = {
        (fila.code, fila.nico)
        for fila in session.execute(
            sa.text(
                "select f.code, n.code as nico from regulatory.nicos n "
                "join regulatory.tariff_fractions f on f.id = n.tariff_fraction_id "
                "where f.valid_to is null"
            )
        )
    }
    unidades = {
        fila[0] for fila in session.execute(sa.text("select code from regulatory.units_of_measure"))
    }
    return Catalogo(igi_por_fraccion=igi, nicos=frozenset(nicos), unidades=frozenset(unidades))


def _catalogo(partida: Mapping[str, Any], donde: str, cat: Catalogo) -> Iterable[Hallazgo]:
    esperado = partida["expected"]
    fraccion, nico, umc = esperado["fraccion"], esperado["nico"], esperado["umc"]

    if fraccion not in cat.igi_por_fraccion:
        yield Hallazgo("fracción", donde, f"{fraccion} no existe o no está vigente")
        return

    if (fraccion, nico) not in cat.nicos:
        yield Hallazgo("NICO", donde, f"el NICO {nico} no existe en {fraccion}")

    declarada = _d(esperado["igi_rate"])
    real = cat.igi_por_fraccion[fraccion]
    if real != declarada:
        yield Hallazgo("IGI", donde, f"el corpus dice {declarada} y la tarifa {real}")

    if umc not in cat.unidades:
        yield Hallazgo("UMC", donde, f"la clave {umc} no está en el Anexo 22")


def _aritmetica(partida: Mapping[str, Any], donde: str) -> Iterable[Hallazgo]:
    """Rehace las cuentas del caso limpio y las compara con lo declarado."""
    e = partida["expected"]
    valor = _d(e["valor_aduana_mxn"])
    igi = valor * _d(e["igi_rate"])
    dta = valor * TASA_DTA
    base_iva = valor + igi + dta

    for campo, calculado, declarado in (
        ("valor en aduana", _d(e["precio_pagado_mxn"]) + _d(e["incrementables_mxn"]), valor),
        ("DTA", dta, _d(e["dta_mxn"])),
        ("IGI", igi, _d(e["igi_mxn"])),
        ("base de IVA", base_iva, _d(e["iva_base_mxn"])),
        ("IVA", base_iva * TASA_IVA, _d(e["iva_mxn"])),
    ):
        if abs(calculado - declarado) > TOLERANCIA:
            yield Hallazgo(
                "aritmética",
                donde,
                f"{campo}: declara {declarado} y sale {calculado.quantize(Decimal('0.01'))}",
            )


def _coherencia(partida: Mapping[str, Any], donde: str) -> Iterable[Hallazgo]:
    """¿Lo observado se desvía de lo esperado exactamente donde el corpus dice?"""
    esperado, observado = partida["expected"], partida["observed"]
    difieren = {campo for campo in esperado if str(esperado[campo]) != str(observado[campo])}
    declarados = {a["field"] for a in partida["anomalies"]}

    if not partida["anomalies"] and difieren:
        yield Hallazgo("limpia contaminada", donde, f"difiere en {sorted(difieren)} sin anomalía")

    # `descripcion_tecnica` no vive en expected/observed: la anomalía de ficha
    # incompleta se siembra recortando la descripción comercial, no un campo.
    for campo in sorted(declarados - difieren - {"descripcion_tecnica"}):
        yield Hallazgo("anomalía fantasma", donde, f"declara anomalía en '{campo}' y no difiere")


def validar(corpus: Mapping[str, Any], catalogo: Catalogo) -> list[Hallazgo]:
    """Todos los defectos del corpus. Lista vacía significa apto para cargar."""
    hallazgos: list[Hallazgo] = []

    for doc_id, documento in sorted(corpus["ground_truth"].items()):
        suma = Decimal(0)
        for partida in documento["parts"]:
            donde = f"{doc_id}/{partida['sec']}"
            suma += _d(partida["observed"]["valor_aduana_mxn"])
            hallazgos.extend(_catalogo(partida, donde, catalogo))
            hallazgos.extend(_aritmetica(partida, donde))
            hallazgos.extend(_coherencia(partida, donde))

        declarado = _d(documento["totals"]["valor_aduana_mxn"])
        if abs(suma - declarado) > TOLERANCIA:
            hallazgos.append(
                Hallazgo(
                    "totales",
                    doc_id,
                    f"las partidas suman {suma.quantize(Decimal('0.01'))} "
                    f"y el encabezado dice {declarado}",
                )
            )

    return hallazgos


def informe(corpus: Mapping[str, Any], hallazgos: list[Hallazgo]) -> str:
    """El informe que se lee antes de decidir si el corpus se carga."""
    documentos = corpus["ground_truth"]
    partidas = sum(len(d["parts"]) for d in documentos.values())
    eventos = Counter(
        a["code"] for d in documentos.values() for p in d["parts"] for a in p["anomalies"]
    )

    lineas = [
        "=" * 72,
        f"CORPUS: {len(documentos)} pedimentos · {partidas} partidas · "
        f"{sum(eventos.values())} anomalías sembradas",
        "=" * 72,
    ]

    if not hallazgos:
        lineas.append("✅ sin defectos: el corpus es apto para cargarse")
    else:
        por_tipo = Counter(h.comprobacion for h in hallazgos)
        lineas.append(f"⚠️  {len(hallazgos)} defectos — el corpus NO debe cargarse así")
        for tipo, n in por_tipo.most_common():
            lineas.append(f"\n  {tipo} ({n}):")
            lineas.extend(
                f"      {h.donde}  {h.detalle}" for h in hallazgos if h.comprobacion == tipo
            )

    lineas.append("-" * 72)
    lineas.extend(f"  {n:>3}  {tipo}" for tipo, n in sorted(eventos.items()))
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("corpus", type=Path, help="JSON consolidado con el ground truth")
    args = parser.parse_args(argv)

    from sqlalchemy.orm import Session

    from apps.api.config import get_settings

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    with Session(sa.create_engine(get_settings().sqlalchemy_url)) as session:
        catalogo = catalogo_desde(session)
        hallazgos = validar(corpus, catalogo)
        session.rollback()

    print(informe(corpus, hallazgos))
    return 1 if hallazgos else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
