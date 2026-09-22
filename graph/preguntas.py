"""Lo que el grafo puede contestar, y lo que nunca.

EL GRAFO NO FUNDAMENTA NADA. Es una proyección de Postgres (§28): lo que
devuelve aquí sirve para MIRAR —qué se repite entre pedimentos, qué comparten
un proveedor y una fracción—, nunca para sostener una afirmación jurídica ni
para calcular dinero. Si una respuesta de aquí acaba en un expediente de
defensa, alguien se saltó el Contrato de Evidencia.

POR QUÉ EN EL GRAFO Y NO EN SQL

Estas tres preguntas atraviesan tres o cuatro tablas y devuelven caminos, no
filas. En SQL son JOINs anidados que hay que reescribir cada vez que cambia la
pregunta; aquí la pregunta ES el camino. Ése es el único motivo por el que el
grafo existe — si una pregunta se contesta mejor en SQL, se contesta en SQL.

LA CYPHER VIVE AQUÍ Y EL DRIVER NO

Este módulo arma consultas y da forma al resultado. Quien las ejecuta cumple
`Consultable`, y el único que lo implementa contra Neo4j es `neo4j_grafo.py`,
que sigue siendo el único archivo que importa el driver (§29).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence


@runtime_checkable
class Consultable(Protocol):
    """Algo capaz de correr una consulta de lectura y devolver filas."""

    def consultar(self, cypher: str, **parametros: Any) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class OperacionDelProveedor:
    """Una partida que este proveedor surtió, con lo que se declaró en ella."""

    pedimento: str
    fecha: str | None
    fraccion: str | None
    descripcion: str | None
    producto: str | None


@dataclass(frozen=True)
class QuienDeclara:
    """Un proveedor que declara cierta fracción, y en cuántas partidas."""

    proveedor: str
    pais: str | None
    partidas: int


@dataclass(frozen=True)
class ClasificacionDelProducto:
    """Una decisión que clasificó este producto, y a qué fracción."""

    decision: str
    fecha: str | None
    estado: str | None
    fraccion: str | None


#: Las partidas de un proveedor, con la fracción que cada una declaró.
#: El camino cruza las dos mitades del grafo: proveedor -> producto -> partida
#: -> pedimento. Antes de `OF_PRODUCT` no existía y esta pregunta no se podía
#: hacer aquí.
_OPERACIONES_DEL_PROVEEDOR = """
MATCH (s:Supplier {id: $proveedor})<-[:SUPPLIED_BY]-(p:Product)
MATCH (p)<-[:OF_PRODUCT]-(i:PedimentoItem)<-[:HAS_ITEM]-(ped:Pedimento)
OPTIONAL MATCH (i)-[:DECLARES]->(f:TariffFraction)
RETURN ped.pedimento_number AS pedimento, toString(ped.operation_date) AS fecha,
       f.code AS fraccion, f.description AS descripcion,
       i.description AS producto
ORDER BY fecha, pedimento
"""

#: Quién más declara una fracción. `OPTIONAL MATCH` a propósito: una partida
#: sin proveedor proyectado se sigue contando y se dice que no se sabe, en vez
#: de desaparecer de la cuenta.
_QUIEN_DECLARA = """
MATCH (f:TariffFraction {code: $fraccion})<-[:DECLARES]-(i:PedimentoItem)
OPTIONAL MATCH (i)-[:OF_PRODUCT]->(:Product)-[:SUPPLIED_BY]->(s:Supplier)
OPTIONAL MATCH (s)-[:LOCATED_IN]->(c:Country)
RETURN coalesce(s.legal_name, '(sin proveedor en el grafo)') AS proveedor,
       c.code AS pais, count(i) AS partidas
ORDER BY partidas DESC, proveedor
"""

#: Cómo se ha clasificado un producto. La fracción sale de la RELACIÓN cuando
#: existe; si no, del código guardado en la decisión — que es lo que pasa
#: cuando ese día no había versión vigente de esa fracción y la arista no se
#: pudo crear (§14). Se prefiere la relación porque apunta a una versión
#: concreta; el código suelto sólo dice el número.
_CLASIFICACIONES = """
MATCH (d:Decision)-[:CLASSIFIES]->(:Product {id: $producto})
OPTIONAL MATCH (d)-[:CLASSIFIED_AS]->(f:TariffFraction)
RETURN d.id AS decision, toString(d.operation_date) AS fecha,
       d.status AS estado, coalesce(f.code, d.fraction_code) AS fraccion
ORDER BY fecha
"""


def operaciones_del_proveedor(grafo: Consultable, proveedor: str) -> list[OperacionDelProveedor]:
    """Qué ha surtido este proveedor, pedimento a pedimento."""
    return [
        OperacionDelProveedor(
            pedimento=f["pedimento"],
            fecha=f["fecha"],
            fraccion=f["fraccion"],
            descripcion=f["descripcion"],
            producto=f["producto"],
        )
        for f in grafo.consultar(_OPERACIONES_DEL_PROVEEDOR, proveedor=proveedor)
    ]


def quien_declara(grafo: Consultable, fraccion: str) -> list[QuienDeclara]:
    """Quién más declara esta fracción. Un patrón, no una acusación."""
    return [
        QuienDeclara(proveedor=f["proveedor"], pais=f["pais"], partidas=f["partidas"])
        for f in grafo.consultar(_QUIEN_DECLARA, fraccion=fraccion)
    ]


def clasificaciones_del_producto(
    grafo: Consultable, producto: str
) -> list[ClasificacionDelProducto]:
    """Cómo se ha clasificado este producto a lo largo del tiempo.

    Dos decisiones con fracciones distintas sobre el mismo producto no dicen
    cuál está mal: dicen que una de las dos lo está, y eso ya es algo que mirar.
    La divergencia formal la emite el Espejo (§18), no esto.
    """
    return [
        ClasificacionDelProducto(
            decision=f["decision"], fecha=f["fecha"], estado=f["estado"], fraccion=f["fraccion"]
        )
        for f in grafo.consultar(_CLASIFICACIONES, producto=producto)
    ]


def informe_del_proveedor(operaciones: Sequence[OperacionDelProveedor]) -> str:
    if not operaciones:
        return "Sin partidas de ese proveedor en el grafo."
    lineas = [f"{len(operaciones)} partidas"]
    lineas += [
        f"  {o.fecha or 's/f':<12} {o.pedimento:<20} {o.fraccion or '—':<10} "
        f"{(o.producto or '')[:40]}"
        for o in operaciones
    ]
    return "\n".join(lineas)
