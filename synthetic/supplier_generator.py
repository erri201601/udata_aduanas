"""`SupplierGenerator` (§24 maestro): elige uno de los 3 proveedores reales
del corpus -- no inventa proveedores nuevos (ver `synthetic/catalog.py`)."""

from __future__ import annotations

from synthetic.catalog import SUPPLIERS, SupplierFicha


def elegir_proveedor(indice: int) -> SupplierFicha:
    """Rota entre los 3 proveedores reales por índice -- determinista, sin
    azar: dos llamadas con el mismo índice devuelven siempre el mismo."""
    return SUPPLIERS[indice % len(SUPPLIERS)]
