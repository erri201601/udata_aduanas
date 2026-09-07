"""Catálogo de atributos del Product DNA (§16 del maestro).

El catálogo es cerrado a propósito. El motor devuelve **siempre** los mismos
atributos, y los que el documento no aporta salen como `MISSING` en vez de
desaparecer. Un atributo ausente que simplemente no aparece en la respuesta es
indistinguible de uno que nadie buscó; uno declarado `MISSING` es una pregunta
abierta que el sistema puede pedirle al importador.

`CRITICOS` son los que cambian la clasificación arancelaria. Que falte uno no
es un hueco cosmético: es la diferencia entre clasificar y no poder hacerlo.
"""

from __future__ import annotations

from typing import Final, Literal

AttributeStatus = Literal["OBSERVED", "EXTRACTED", "INFERRED", "MISSING"]

#: Los cuatro estados de §16, en orden de menor a mayor distancia del documento.
ATTRIBUTE_STATUSES: Final[tuple[AttributeStatus, ...]] = (
    "OBSERVED",
    "EXTRACTED",
    "INFERRED",
    "MISSING",
)

#: Estados sobre los que se puede sostener una clasificación. `INFERRED`
#: acompaña pero no sostiene: es una deducción del modelo, no del documento.
SOLID_STATUSES: Final[frozenset[str]] = frozenset({"OBSERVED", "EXTRACTED"})

#: Salida de §16, en el orden del documento rector.
CATALOG: Final[tuple[str, ...]] = (
    "product_name",
    "commercial_name",
    "manufacturer",
    "brand",
    "model",
    "sku",
    "function",
    "materials",
    "composition",
    "dimensions",
    "weight",
    "voltage",
    "power",
    "capacity",
    "industry",
    "intended_use",
    "country_of_manufacture",
    "technical_attributes",
)

#: Sin estos, clasificar es adivinar. `function` y `materials` deciden la
#: partida; `composition` desempata en textiles y plásticos; `intended_use`
#: distingue mercancías idénticas con destinos distintos; `country_of_manufacture`
#: determina trato arancelario preferencial y cuotas compensatorias.
CRITICOS: Final[frozenset[str]] = frozenset(
    {
        "function",
        "materials",
        "composition",
        "intended_use",
        "country_of_manufacture",
    }
)

#: Unidad esperada, cuando el atributo la tiene. Sirve para no aceptar "2.5"
#: a secas donde hacen falta kilogramos.
UNIDADES: Final[dict[str, str]] = {
    "weight": "kg",
    "dimensions": "mm",
    "voltage": "V",
    "power": "W",
    "capacity": "L",
}


def es_conocido(name: str) -> bool:
    """¿Pertenece al catálogo de §16?"""
    return name in CATALOG


def es_critico(name: str) -> bool:
    """¿Su ausencia impide clasificar?"""
    return name in CRITICOS
