"""Tests de las preguntas al grafo (§28).

Con un grafo de mentira, igual que la proyección: CI no tiene Neo4j y no se
finge que sí. Lo que se fija aquí es que la Cypher pida los campos que el
grafo REALMENTE tiene —eso ya falló una vez— y que ninguna respuesta se
presente como fundamento.
"""

from __future__ import annotations

from typing import Any

import pytest
from graph.preguntas import (
    Consultable,
    clasificaciones_del_producto,
    informe_del_proveedor,
    operaciones_del_proveedor,
    quien_declara,
)

pytestmark = pytest.mark.unit


class GrafoQueResponde:
    """Devuelve lo que se le diga y guarda qué le preguntaron."""

    def __init__(self, filas: list[dict[str, Any]] | None = None) -> None:
        self.filas = filas or []
        self.cypher = ""
        self.parametros: dict[str, Any] = {}

    def consultar(self, cypher: str, **parametros: Any) -> list[dict[str, Any]]:
        self.cypher, self.parametros = cypher, parametros
        return self.filas


def test_el_grafo_falso_cumple_el_puerto() -> None:
    assert isinstance(GrafoQueResponde(), Consultable)


def test_las_operaciones_de_un_proveedor_cruzan_las_dos_mitades() -> None:
    """Proveedor -> producto -> partida -> pedimento.

    Antes de `OF_PRODUCT` este camino no existía: el grafo eran dos grafos sin
    una sola arista entre ellos, y esta pregunta no se podía hacer.
    """
    g = GrafoQueResponde(
        [
            {
                "pedimento": "24 06 3801 4000123",
                "fecha": "2026-03-04",
                "fraccion": "84713001",
                "descripcion": "Unidades de proceso",
                "producto": "Laptop 14",
            }
        ]
    )

    (o,) = operaciones_del_proveedor(g, "prov-1")

    assert o.pedimento == "24 06 3801 4000123"
    assert g.parametros == {"proveedor": "prov-1"}
    assert ":OF_PRODUCT" in g.cypher, "sin esa arista la pregunta no tiene camino"
    assert "pedimento_number" in g.cypher, "la propiedad del nodo se llama así, no `number`"


def test_quien_declara_no_pierde_la_partida_sin_proveedor() -> None:
    """Un `MATCH` obligatorio la habría hecho desaparecer de la cuenta."""
    g = GrafoQueResponde(
        [{"proveedor": "(sin proveedor en el grafo)", "pais": None, "partidas": 3}]
    )

    (q,) = quien_declara(g, "84713001")

    assert q.partidas == 3
    assert "OPTIONAL MATCH" in g.cypher


def test_la_fraccion_de_una_decision_sale_de_la_relacion_antes_que_del_texto() -> None:
    """La arista apunta a una VERSIÓN vigente; el código suelto sólo es un número.

    Cuando ese día no regía ninguna versión de esa fracción, la arista no se
    crea (§14) y sólo queda el código. Se devuelve, pero el orden del
    `coalesce` dice cuál vale más.
    """
    g = GrafoQueResponde(
        [{"decision": "d1", "fecha": "2026-03-04", "estado": "RESOLVED", "fraccion": "84713001"}]
    )

    (c,) = clasificaciones_del_producto(g, "prod-1")

    assert c.fraccion == "84713001"
    assert "coalesce(f.code, d.fraction_code)" in g.cypher


def test_un_proveedor_sin_partidas_lo_dice_en_vez_de_imprimir_vacio() -> None:
    assert "Sin partidas" in informe_del_proveedor([])


def test_ninguna_pregunta_escribe() -> None:
    """Las cuatro consultas son de lectura. Una escritura aquí ensuciaría la
    proyección con datos que no salen de Postgres, y el grafo dejaría de ser
    proyección para volverse fuente."""
    from graph import preguntas

    cypher = " ".join(
        v for k, v in vars(preguntas).items() if k.startswith("_") and isinstance(v, str)
    ).upper()

    for prohibida in ("CREATE", "MERGE", "DELETE", "SET ", "REMOVE"):
        assert prohibida not in cypher, f"una pregunta no {prohibida.strip().lower()}"


def test_los_ejemplos_del_cli_usan_banderas_que_existen() -> None:
    """Un ejemplo con una bandera inventada manda a quien lo copia a un error.

    Ya pasó con el slug del corpus en la métrica del §26: el ejemplo parecía
    correcto y no lo era. Aquí el docstring es la ayuda que ve la gente, así
    que se cruza con el parser.
    """
    import re

    from graph import preguntar

    assert preguntar.__doc__ is not None
    # Sólo las líneas de EJEMPLO: el texto puede nombrar una bandera para
    # explicar que no existe, y eso no es un ejemplo roto.
    ejemplos = [linea for linea in preguntar.__doc__.splitlines() if "python -m" in linea]
    assert ejemplos, "el docstring dejó de enseñar cómo se corre"

    banderas = {b for linea in ejemplos for b in re.findall(r"--[a-z]+", linea)}

    assert banderas <= {"--proveedor", "--fraccion", "--producto"}, (
        f"los ejemplos inventan {banderas - {'--proveedor', '--fraccion', '--producto'}}"
    )
