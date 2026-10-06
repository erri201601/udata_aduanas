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

QUÉ CUENTA COMO PENDIENTE (6-oct)

Lo decide `database.repositories.preguntas`, el mismo sitio que usan la bandeja
de la consola (`GET /review/preguntas`) y el recálculo al contestar. Este
script tenía su propia consulta —con `status` en vez de la bandera, la última
decisión por producto en vez de por ficha, y un filtro de «ya contestadas» que
miraba sólo el lado de la tarifa— y por eso la terminal no enseñaba la
pregunta de 8481 mientras la bandeja sí. Ahora sólo imprime.
"""

from __future__ import annotations

import argparse

from database.repositories.preguntas import preguntas_pendientes, productos_por_id


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
        grupos = preguntas_pendientes(sesion)
        ids = [d.product_id for g in grupos for d in g.decisiones if d.product_id]
        skus = {pid: p.sku for pid, p in productos_por_id(sesion, list(dict.fromkeys(ids))).items()}
    finally:
        sesion.rollback()
        sesion.close()
        motor.dispose()

    if not grupos:
        print("No hay preguntas pendientes.")
        return 0

    casos = {d.id for g in grupos for d in g.decisiones}
    print(f"{len(grupos)} preguntas desatascarían {len(casos)} casos.\n")
    print("Ordenadas por cuánto rinde cada una.\n")
    for g in grupos:
        print(f"── {len(g.decisiones)} caso(s) · posición {g.codigo}")
        print(f"   La tarifa exige: «{g.exige}»")
        # Las fichas que caen aquí. Si son varias distintas, se enseñan: la
        # respuesta puede no ser la misma para todas, y quien contesta tiene
        # que poder verlo.
        for ficha in sorted(g.fichas)[:3]:
            print(f"   La ficha dice:   {ficha}")
        print("   ¿La cumple?   [sí / no]")
        ejemplos = sorted({skus[d.product_id] for d in g.decisiones if d.product_id in skus})
        print(f"   ejemplos: {', '.join(ejemplos[:4])}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
