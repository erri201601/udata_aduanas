"""Adaptador de Neo4j. El ÚNICO archivo del repo que importa su driver (§29).

Las etiquetas y los tipos de relación no se pueden pasar como parámetro en
Cypher —sólo los valores— así que van interpolados. Por eso se validan contra
`_IDENTIFICADOR` antes de tocar la consulta: interpolar sin validar es como se
escribe una inyección, aunque hoy todos los nombres salgan de constantes
nuestras.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

import structlog

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

log = structlog.stdlib.get_logger("graph.neo4j")

#: Nombres admitidos para etiquetas, tipos y claves.
_IDENTIFICADOR: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Cuántas filas por transacción. El catálogo son ~20 mil nodos: en un solo
#: `UNWIND` cabe, pero un lote acotado deja el uso de memoria predecible.
LOTE: Final = 5_000


def _valida(nombre: str) -> str:
    if not _IDENTIFICADOR.match(nombre):
        raise ValueError(f"identificador de Cypher no admitido: {nombre!r}")
    return nombre


class Neo4jGrafo:
    """`Grafo` respaldado por Neo4j."""

    def __init__(self, driver: Any, *, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    def _correr(self, consulta: str, **parametros: Any) -> list[Any]:
        with self._driver.session(database=self._database) as sesion:
            return list(sesion.run(consulta, **parametros))

    def merge_nodos(
        self, etiqueta: str, filas: Sequence[Mapping[str, Any]], *, clave: str = "id"
    ) -> int:
        etiqueta, clave = _valida(etiqueta), _valida(clave)
        if not filas:
            return 0
        consulta = f"UNWIND $filas AS f MERGE (n:{etiqueta} {{{clave}: f.{clave}}}) SET n += f"
        for i in range(0, len(filas), LOTE):
            self._correr(consulta, filas=list(filas[i : i + LOTE]))
        log.info("graph.nodos", etiqueta=etiqueta, filas=len(filas))
        return len(filas)

    def merge_relaciones(
        self,
        tipo: str,
        origen: str,
        destino: str,
        pares: Sequence[tuple[str, str]],
        *,
        clave_origen: str = "id",
        clave_destino: str = "id",
    ) -> int:
        tipo, origen, destino = _valida(tipo), _valida(origen), _valida(destino)
        clave_origen, clave_destino = _valida(clave_origen), _valida(clave_destino)
        if not pares:
            return 0
        consulta = (
            f"UNWIND $pares AS p "
            f"MATCH (a:{origen} {{{clave_origen}: p.origen}}), "
            f"(b:{destino} {{{clave_destino}: p.destino}}) "
            f"MERGE (a)-[:{tipo}]->(b)"
        )
        datos = [{"origen": o, "destino": d} for o, d in pares]
        for i in range(0, len(datos), LOTE):
            self._correr(consulta, pares=datos[i : i + LOTE])
        log.info("graph.relaciones", tipo=tipo, pares=len(pares))
        return len(pares)

    def conteos(self) -> dict[str, int]:
        """Lo que hay DE VERDAD en el grafo, para demostrar la idempotencia."""
        nodos = self._correr(
            "MATCH (n) UNWIND labels(n) AS etiqueta RETURN etiqueta AS clave, count(*) AS total"
        )
        relaciones = self._correr("MATCH ()-[r]->() RETURN type(r) AS clave, count(r) AS total")
        return {fila["clave"]: fila["total"] for fila in [*nodos, *relaciones]}
