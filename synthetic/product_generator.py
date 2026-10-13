"""`ProductGenerator` (§24 maestro): una partida nueva a partir de una ficha
de catálogo YA existente (`synthetic/catalog.py`) -- nunca inventa un
producto nuevo. Lo único que decide esta pieza es, por partida, el
`technical_spec` (completo o recortado) y, cuando el escenario lo pide, un
`sku_override` compartido con otra partida de otro pedimento.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic.catalog import ProductFicha


@dataclass(frozen=True)
class PartidaProducto:
    product_id: str
    commercial_description: str
    technical_spec: dict[str, object]
    #: `None` = sku normal, único por partida (misma convención que
    #: `ingestion/sintetico/load.py::_create_product_con_dna`). Con valor,
    #: dos partidas de PEDIMENTOS DISTINTOS comparan como el mismo SKU --
    #: la precondición de `INCONSISTENT_SKU_CLASSIFICATION` (§25 maestro).
    sku_override: str | None = field(default=None)


def generar_partida(ficha: ProductFicha, *, sku_override: str | None = None) -> PartidaProducto:
    """La ficha completa, sin recortar -- declaración limpia."""
    return PartidaProducto(
        product_id=ficha.id,
        commercial_description=ficha.description,
        technical_spec=dict(ficha.spec),
        sku_override=sku_override,
    )
