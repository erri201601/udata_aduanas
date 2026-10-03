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
"""

from __future__ import annotations

import argparse
from collections import defaultdict

import sqlalchemy as sa

_PENDIENTES = sa.text(
    """
    SELECT p.sku,
           q->>'atributo'        AS atributo,
           q->>'valor_declarado' AS dice_la_ficha,
           q->>'exige'           AS exige_la_tarifa,
           q->>'codigo'          AS posicion,
           q->>'texto'           AS pregunta
    FROM intelligence.classification_decisions d
    JOIN operational.products p ON p.id = d.product_id
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(d.rgi_trace -> -1 -> 'preguntas', '[]'::jsonb)
    ) AS q
    WHERE d.data_origin <> 'HUMAN_VALIDATED'
      AND d.status = 'HUMAN_REVIEW_REQUIRED'
      -- Sólo la decisión vigente de cada producto: las viejas preguntan por
      -- un texto de tarifa que quizá ya cambió.
      AND d.created_at = (
        SELECT MAX(o.created_at) FROM intelligence.classification_decisions o
        WHERE o.product_id = d.product_id AND o.data_origin <> 'HUMAN_VALIDATED'
      )
      -- Y no las ya contestadas: el bucle no vuelve a preguntar.
      AND NOT EXISTS (
        SELECT 1 FROM regulatory.nomenclature_synonyms s
        WHERE lower(s.nomenclature_term) = lower(q->>'exige')
          AND s.data_origin = 'HUMAN_VALIDATED'
      )
    """
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", default="local", choices=["local", "shared"])
    args = parser.parse_args(argv)

    from sqlalchemy.orm import Session as SesionSql

    from apps.api.config import url_de_postgres

    motor = sa.create_engine(url_de_postgres(args.target))
    sesion = SesionSql(motor)
    try:
        filas = sesion.execute(_PENDIENTES).all()
    finally:
        sesion.rollback()
        sesion.close()
        motor.dispose()

    # Agrupadas por la PAREJA, no por caso: la misma pregunta en veinte
    # productos es una pregunta, no veinte.
    por_pareja: dict[tuple[str, str], list[str]] = defaultdict(list)
    posicion: dict[tuple[str, str], str] = {}
    for f in filas:
        clave = (f.dice_la_ficha, f.exige_la_tarifa)
        por_pareja[clave].append(f.sku)
        posicion[clave] = f.posicion

    if not por_pareja:
        print("No hay preguntas pendientes.")
        return 0

    print(f"{len(por_pareja)} preguntas desatascarían {len(filas)} casos.\n")
    print("Ordenadas por cuánto rinde cada una.\n")
    for (ficha, tarifa), skus in sorted(por_pareja.items(), key=lambda x: -len(x[1])):
        print(f"── {len(skus)} caso(s) · posición {posicion[(ficha, tarifa)]}")
        print(f"   La ficha dice: «{ficha}»")
        print(f"   La tarifa exige: «{tarifa}»")
        print("   ¿Son lo mismo?   [sí / no]")
        print(f"   ejemplos: {', '.join(sorted(set(skus))[:4])}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
