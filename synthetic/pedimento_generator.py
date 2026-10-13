"""`PedimentoGenerator` (§24 maestro): ensambla un pedimento completo en la
MISMA forma de `dict` que ya parsea `ingestion.sintetico.corpus_espejo.
parse_corpus` -- no un pipeline nuevo. Lo que genera este paquete se monta
sobre el mismo PARSED -> DATABASE ya revisado, en vez de duplicarlo.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from synthetic.catalog import ENTRY_CUSTOMS, PEDIMENTO_KEY, PRODUCT_CATALOG, REGIME, SupplierFicha
from synthetic.invoice_generator import calcular

if TYPE_CHECKING:
    from synthetic.company_generator import CompanyFicha
    from synthetic.errors import AnomalySpec
    from synthetic.product_generator import PartidaProducto

_IGI_RATE_DEFAULT = Decimal("0.35")


@dataclass(frozen=True)
class PartidaPlan:
    """Lo que hace falta para generar UNA partida: su producto, cantidad,
    y las anomalías (si alguna) que `ErrorInjector` ya decidió."""

    partida: PartidaProducto
    cantidad_umc: int
    umc: str = "3"  # metro lineal -- misma UMC que el corpus real para cable
    igi_rate: Decimal = _IGI_RATE_DEFAULT
    pais_origen: str = "CHN"
    #: Si se da, SOBRESCRIBE la fracción "correcta" del catálogo --
    #: `INCONSISTENT_SKU_CLASSIFICATION` la usa para declarar una fracción
    #: distinta de la que el mismo SKU ya declaró en otro pedimento.
    fraccion_override: str | None = None
    incrementables_mxn: Decimal | None = None
    #: Si se da, es el importe que debería haberse declarado --
    #: `MISSING_INCREMENTABLE` lo usa para calcular `expected` con el
    #: concepto incluido y `observed` sin él.
    incrementables_correcto_mxn: Decimal | None = None
    net_weight_kg: Decimal | None = None
    identifiers: dict[str, str] | None = None
    anomalies: tuple[AnomalySpec, ...] = ()

    @property
    def precio_unitario_mxn(self) -> Decimal:
        # Mismo orden de magnitud que el corpus real (~2 000-3 000 MXN/m).
        return Decimal("2500.00")


def _construir_partida(sec: int, plan: PartidaPlan) -> tuple[dict[str, object], Decimal]:
    ficha = PRODUCT_CATALOG[plan.partida.product_id]
    fraccion = plan.fraccion_override or ficha.fraction_code
    cantidad = Decimal(plan.cantidad_umc)
    precio_pagado_mxn = (plan.precio_unitario_mxn * cantidad).quantize(Decimal("0.01"))

    incrementables_declarado = (
        plan.incrementables_mxn
        if plan.incrementables_mxn is not None
        else (precio_pagado_mxn * Decimal("0.03")).quantize(Decimal("0.01"))
    )
    montos = calcular(
        precio_pagado_mxn=precio_pagado_mxn,
        incrementables_mxn=incrementables_declarado,
        igi_rate=plan.igi_rate,
    )

    observado: dict[str, object] = {
        "fraccion": fraccion,
        "nico": ficha.nico_code,
        "umc": plan.umc,
        "umt": "1",
        "cantidad_umc": plan.cantidad_umc,
        "cantidad_umt": float(cantidad),
        "igi_rate": float(plan.igi_rate),
        "iva_rate": float(montos.iva_rate),
        "precio_pagado_mxn": float(montos.precio_pagado_mxn),
        "incrementables_mxn": float(montos.incrementables_mxn),
        "valor_aduana_mxn": float(montos.valor_aduana_mxn),
        "dta_mxn": float(montos.dta_mxn),
        "igi_mxn": float(montos.igi_mxn),
        "iva_base_mxn": float(montos.iva_base_mxn),
        "iva_mxn": float(montos.iva_mxn),
        "pais_origen": plan.pais_origen,
    }
    if plan.partida.sku_override is not None:
        observado["sku_override"] = plan.partida.sku_override
    if plan.net_weight_kg is not None:
        observado["net_weight_kg"] = float(plan.net_weight_kg)
    if plan.identifiers is not None:
        observado["identifiers"] = plan.identifiers

    esperado = dict(observado)
    if plan.fraccion_override is not None:
        # `expected` siempre es la fracción real del catálogo -- la
        # sobrescritura sólo va en `observed`, es lo que hace que la
        # anomalía exista.
        esperado["fraccion"] = ficha.fraction_code
    if plan.incrementables_correcto_mxn is not None:
        montos_correctos = calcular(
            precio_pagado_mxn=precio_pagado_mxn,
            incrementables_mxn=plan.incrementables_correcto_mxn,
            igi_rate=plan.igi_rate,
        )
        esperado["incrementables_mxn"] = float(montos_correctos.incrementables_mxn)
        esperado["valor_aduana_mxn"] = float(montos_correctos.valor_aduana_mxn)

    parte: dict[str, object] = {
        "sec": str(sec),
        "product_id": plan.partida.product_id,
        "commercial_description": plan.partida.commercial_description,
        "technical_spec": plan.partida.technical_spec,
        "classification_evaluable": True,
        "classification_reason": "ficha completa",
        "expected": esperado,
        "observed": observado,
        "anomalies": [a.as_json() for a in plan.anomalies],
    }
    return parte, montos.valor_aduana_mxn


def construir_pedimento(
    *,
    document_id: str,
    pedimento_number: str,
    importador: CompanyFicha,
    proveedor: SupplierFicha,
    date_entry: str,
    date_payment: str,
    exchange_rate: Decimal,
    partidas: list[PartidaPlan],
    pedimento_key: str = PEDIMENTO_KEY,
    rectifies_pedimento_number: str | None = None,
    rectification_number: int | None = None,
) -> dict[str, object]:
    """Un pedimento completo, en la forma que `parse_corpus` espera bajo
    `ground_truth[document_id]`."""
    construidas = [_construir_partida(i + 1, plan) for i, plan in enumerate(partidas)]
    partes = [parte for parte, _ in construidas]
    total_valor_aduana = sum((valor for _, valor in construidas), start=Decimal("0"))
    pedimento: dict[str, object] = {
        "document_id": document_id,
        "is_simulation": True,
        "pedimento_number": pedimento_number,
        "operation": "IMP",
        "pedimento_key": pedimento_key,
        "regime": REGIME,
        "exchange_rate": float(exchange_rate),
        "entry_customs": ENTRY_CUSTOMS,
        "date_entry": date_entry,
        "date_payment": date_payment,
        "importer": {
            "rfc": importador.rfc,
            "name": importador.name,
            "address": importador.address,
        },
        "provider": {
            "name": proveedor.name,
            "address": proveedor.address,
            "country": proveedor.country,
            "incoterm": proveedor.incoterm,
            "currency": proveedor.currency,
        },
        "totals": {"valor_aduana_mxn": float(total_valor_aduana)},
        "parts": partes,
    }
    if rectifies_pedimento_number is not None:
        pedimento["rectifies_pedimento_number"] = rectifies_pedimento_number
    if rectification_number is not None:
        pedimento["rectification_number"] = rectification_number
    return pedimento
