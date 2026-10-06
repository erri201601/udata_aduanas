"""Las preguntas que el motor tiene sin responder, agrupadas y sin repetir.

PARA QUÉ SIRVE

El bucle de captura hace que el motor formule una pregunta concreta cuando se
atasca. Esto las junta todas, quita las repetidas y las ordena por cuántos
casos desatascaría cada una — para que el tiempo de un clasificador vaya a lo
que más rinde.

Medido el 2-oct: 52 decisiones atascadas en ocho familias. La misma duda una y
otra vez. Una respuesta no resuelve un caso: resuelve su familia entera.

CÓMO SE CONTESTA

    POST /review/vocabulario
    {"termino_ficha": "...", "termino_tarifa": "...",
     "son_lo_mismo": false, "reviewer": "nombre", "nota": "por qué"}

El `no` vale tanto como el `sí`: es el que descarta.

QUÉ CUENTA COMO PENDIENTE (ADR 0008, 6-oct)

Lo decide `database.repositories.preguntas.pendientes`, lo mismo que la bandeja
y el recálculo al contestar. Este script tenía su propia consulta —`status` en
vez de la bandera, la última decisión por producto en vez de por ficha— y un
filtro de «ya contestadas» que miraba sólo el lado de la tarifa: el defecto que
`core.rgi_engine.pregunta._ya_esta_contestada` existe para evitar. Ni siquiera
miraba `kind`, así que un EXCLUYE sobre tuberías callaba la pregunta de un
sartén. Por eso la terminal no enseñaba la pregunta de 8481 y la bandeja sí.

Ahora enseña lo que el motor dejó en la traza, agrupado. Cuenta CASOS
distintos, no filas: sus cifras pueden no coincidir con las de antes.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from database.models import Product
from database.repositories.preguntas import pendientes, preguntas_de


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", default="local", choices=["local", "shared"])
    args = parser.parse_args(argv)

    import sqlalchemy as sa
    from sqlalchemy.orm import Session as SesionSql

    from apps.api.config import url_de_postgres

    motor = sa.create_engine(url_de_postgres(args.target))
    sesion = SesionSql(motor)
    try:
        casos = sesion.scalars(pendientes()).all()
        ids = {c.product_id for c in casos if c.product_id is not None}
        skus = dict(
            sesion.execute(sa.select(Product.id, Product.sku).where(Product.id.in_(ids))).tuples()
        )
    finally:
        sesion.rollback()
        sesion.close()
        motor.dispose()

    # Agrupadas por LO QUE EXIGE LA TARIFA en su posición, no por caso: la
    # misma cláusula en veinte productos es una pregunta, no veinte.
    por_clausula: dict[tuple[str, str], set[str]] = defaultdict(set)
    fichas: dict[tuple[str, str], set[str]] = defaultdict(set)
    con_pregunta: set[str] = set()
    for caso in casos:
        for q in preguntas_de(caso):
            clave = (str(q["codigo"]), str(q["exige"]))
            sku = skus.get(caso.product_id) if caso.product_id else None
            por_clausula[clave].add(sku or str(caso.id))
            con_pregunta.add(str(caso.id))
            if q.get("mercancia"):
                fichas[clave].add(str(q["mercancia"]))

    print(f"{len(casos)} casos pendientes; {len(con_pregunta)} llevan pregunta.\n")
    if not por_clausula:
        print("No hay preguntas pendientes.")
        return 0

    print(f"{len(por_clausula)} preguntas, ordenadas por cuánto rinde cada una.\n")
    for (posicion, tarifa), skus_caso in sorted(
        por_clausula.items(), key=lambda x: (-len(x[1]), x[0])
    ):
        print(f"── {len(skus_caso)} caso(s) · posición {posicion}")
        print(f"   La tarifa exige: «{tarifa}»")
        # Las fichas que caen aquí. Si son varias distintas, se enseñan: la
        # respuesta puede no ser la misma para todas, y quien contesta tiene
        # que poder verlo.
        for ficha in sorted(fichas[(posicion, tarifa)])[:3]:
            print(f"   La ficha dice:   {ficha}")
        print("   ¿La cumple?   [sí / no]")
        print(f"   ejemplos: {', '.join(sorted(skus_caso)[:4])}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
