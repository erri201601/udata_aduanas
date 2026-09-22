"""Corre la proyección: `python -m graph.proyectar --target local|shared`.

Lee de Postgres y escribe en Neo4j. Nunca al revés, y nunca escribe en
Postgres: la sesión se cierra con rollback.

OJO CON `--target` SI CORRES DESDE EL DEV SERVER

El nombre engaña ahí, y le mordió a Persona 1 (22-sep). En udata-nitro la
infraestructura compartida ES la local: Postgres, MinIO y Neo4j viven en esa
máquina y el resto del equipo los alcanza por Tailscale. Así que desde el
servidor hay que usar `--target local` para apuntar a lo compartido, y
`--target shared` falla pidiendo `ADUANERO_SHARED_URL`, que allí no existe.

`shared` significa «alcanzar la infraestructura del equipo DESDE FUERA», no
«la base del equipo». Se deja el nombre como está para no romper los otros
comandos que ya lo usan —`rag.backfill_embeddings` entre ellos— pero queda
dicho aquí y en el `--help`.

La contraseña de Neo4j sale de `.env` como el resto de credenciales (§9). Si
no está, no se inventa un valor por omisión: se dice y se sale.
"""

from __future__ import annotations

import argparse
import os
from typing import TYPE_CHECKING

import structlog
from apps.api.config import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from graph.neo4j_grafo import Neo4jGrafo
from graph.proyeccion import proyectar

if TYPE_CHECKING:
    from graph.proyeccion import Resumen

log = structlog.stdlib.get_logger("graph.proyectar")


def _url_postgres(target: str) -> str:
    if target == "shared":
        url = os.environ.get("ADUANERO_SHARED_URL")
        if not url:
            raise SystemExit(
                "ADUANERO_SHARED_URL no está definida. La contraseña la entrega "
                "Persona 1 por canal seguro — nunca por chat ni en el código."
            )
        return url
    return get_settings().sqlalchemy_url


def _driver() -> object:
    from neo4j import GraphDatabase

    ajustes = get_settings()
    clave = ajustes.neo4j_password.get_secret_value()
    if not clave:
        raise SystemExit(
            "NEO4J_PASSWORD no está en .env. Sin credencial no se proyecta: "
            "un valor por omisión sería una contraseña en el código."
        )
    return GraphDatabase.driver(ajustes.neo4j_uri, auth=(ajustes.neo4j_user, clave))


def informe(resumen: Resumen, antes: dict[str, int], despues: dict[str, int]) -> str:
    """Los números, y la prueba de que correrlo otra vez no los cambia."""
    lineas = [f"NODOS ({resumen.total_nodos})"]
    lineas += [f"  {e:<16} {n:>7}" for e, n in sorted(resumen.nodos.items())]
    lineas.append(f"RELACIONES ({resumen.total_relaciones})")
    lineas += [f"  {t:<16} {n:>7}" for t, n in sorted(resumen.relaciones.items())]
    lineas.append("EN EL GRAFO, ANTES Y DESPUÉS DE LA SEGUNDA CORRIDA")
    for clave in sorted(set(antes) | set(despues)):
        marca = "=" if antes.get(clave) == despues.get(clave) else "≠ CAMBIÓ"
        lineas.append(
            f"  {clave:<16} {antes.get(clave, 0):>7} → {despues.get(clave, 0):>7}  {marca}"
        )
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        required=True,
        choices=["local", "shared"],
        help=(
            "De dónde se lee Postgres. DESDE EL DEV SERVER usa 'local': ahí la "
            "infraestructura compartida es la local, y 'shared' falla pidiendo "
            "ADUANERO_SHARED_URL, que en esa máquina no existe. 'shared' es para "
            "alcanzar la infraestructura del equipo desde otra máquina."
        ),
    )
    parser.add_argument(
        "--dos-veces",
        action="store_true",
        help="Corre la proyección dos veces y compara los conteos: la idempotencia se demuestra.",
    )
    args = parser.parse_args(argv)

    grafo = Neo4jGrafo(_driver())
    motor = create_engine(_url_postgres(args.target))
    with Session(motor) as sesion:
        try:
            resumen = proyectar(sesion, grafo)
            antes = grafo.conteos()
            despues = antes
            if args.dos_veces:
                proyectar(sesion, grafo)
                despues = grafo.conteos()
        finally:
            sesion.rollback()

    print(informe(resumen, antes, despues))
    log.info("graph.proyectado", nodos=resumen.total_nodos, relaciones=resumen.total_relaciones)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
