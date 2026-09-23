"""Pregúntale al grafo. Lectura, y nada que fundamente nada.

    python -m graph.preguntar --fraccion 84713001
    python -m graph.preguntar --proveedor <uuid>
    python -m graph.preguntar --producto <uuid>

El grafo es una proyección de Postgres (§28). Lo que sale de aquí sirve para
ver patrones entre operaciones —quién más declara esta fracción, en qué
pedimentos apareció este producto—, nunca para sostener una afirmación
jurídica ni para calcular dinero. Para eso están el motor y el Contrato de
Evidencia.

No lleva `--target`, y no es un olvido: las otras herramientas eligen entre la
Postgres local y la del equipo, pero aquí no se lee Postgres. El grafo es
siempre el que digan NEO4J_URI y NEO4J_PASSWORD, que no se escriben en el
código ni en `.env` compartido.
"""

from __future__ import annotations

import argparse

import structlog

from graph.preguntas import (
    clasificaciones_del_producto,
    informe_del_proveedor,
    operaciones_del_proveedor,
    quien_declara,
)

log = structlog.stdlib.get_logger("graph.preguntar")


def _driver() -> object:
    from apps.api.config import get_settings
    from neo4j import GraphDatabase

    ajustes = get_settings()
    clave = ajustes.neo4j_password.get_secret_value()
    if not clave:
        raise SystemExit(
            "NEO4J_PASSWORD no está definida. La entrega Persona 1 por canal "
            "seguro — nunca por chat ni en el código."
        )
    return GraphDatabase.driver(ajustes.neo4j_uri, auth=(ajustes.neo4j_user, clave))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pregunta = parser.add_mutually_exclusive_group(required=True)
    pregunta.add_argument("--proveedor", help="UUID del proveedor: qué ha surtido y dónde")
    pregunta.add_argument("--fraccion", help="Código de 8 dígitos: quién más la declara")
    pregunta.add_argument("--producto", help="UUID del producto: cómo se ha clasificado")
    args = parser.parse_args(argv)

    from graph.neo4j_grafo import Neo4jGrafo

    grafo = Neo4jGrafo(_driver())

    if args.proveedor:
        print(informe_del_proveedor(operaciones_del_proveedor(grafo, args.proveedor)))
    elif args.fraccion:
        declarantes = quien_declara(grafo, args.fraccion)
        if not declarantes:
            print(f"Nadie declara {args.fraccion} en el grafo.")
        for d in declarantes:
            print(f"  {d.partidas:>3} partidas  {d.pais or '--'}  {d.proveedor}")
    else:
        historial = clasificaciones_del_producto(grafo, args.producto)
        if not historial:
            print("Ese producto no tiene decisiones proyectadas.")
        for c in historial:
            print(f"  {c.fecha or 's/f':<12} {c.estado or '?':<26} {c.fraccion or '—'}")

    print("\nEl grafo es proyección: esto se mira, no se cita.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
