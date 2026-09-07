"""Money Finder — cálculo determinista de contribuciones.

§22 del maestro: los cálculos monetarios se hacen con código, con `Decimal` y
nunca con `float`. **Jamás se le pide a un modelo que calcule.** Un modelo
explica un resultado ya calculado; no lo produce, porque no hay forma de
auditar una aritmética que salió de una red neuronal.

USO

    from decimal import Decimal
    from core.taxation import Money, TaxRates, compute_taxes, compute_divergence

    tasas = TaxRates(
        igi_rate=Decimal("0.15"),
        iva_rate=Decimal("0.16"),
        dta_rate=Decimal("0.008"),
        source_ids=(id_de_la_fraccion,),
    )

    calculo = compute_taxes(
        transaction_value=Money(amount=Decimal("100000.00"), currency="MXN"),
        incrementables=[Money(amount=Decimal("8000.00"), currency="MXN")],
        rates=tasas,
    )

    calculo.total_taxes      # Money
    calculo.explain()        # el desglose, listo para que un LLM lo narre
    calculo.assumptions      # lo que se dio por supuesto

    impacto = compute_divergence(declared=lo_declarado, expected=lo_esperado)
    impacto.direction        # OMISION | SOBREPAGO | SIN_DIFERENCIA
    impacto.as_money_impact()  # para Dossier.money_impact del Evidence Contract

QUÉ GARANTIZA

- Ningún `float` toca un importe. El constructor de `Money` lo rechaza.
- No se suman divisas distintas sin un tipo de cambio explícito.
- Una tasa mayor que 1 se rechaza: casi siempre es un 16 que debía ser 0.16.
- Todo cálculo expone fórmula, entradas, versión y supuestos, así que se puede
  repetir a mano y llegar al mismo número.
- `is_simulation` por defecto `True`: mientras no conste que los datos son
  reales, el resultado se presenta como simulación (§33).

QUÉ NO HACE

**No conoce ninguna tasa.** Las recibe en `TaxRates`. Codificar «IGI 15%» aquí
sería inventar fundamento jurídico (§8.1) y congelarlo: el día que cambiara en
el DOF, el sistema seguiría calculando con la anterior sin que nadie lo note.
Las tasas salen de `regulatory.tariff_fractions`, con su vigencia y su fuente.

Tampoco convierte divisas por su cuenta: `Money.convert()` exige un tipo de
cambio explícito, porque elegir el FIX de un día u otro cambia el resultado.

PENDIENTE

Las reglas exactas de redondeo del pedimento están en el Anexo 22 y no se han
contrastado. El motor redondea a dos decimales por contribución, media hacia
arriba, y lo declara en `assumptions` como NEEDS_VALIDATION. Tampoco calcula
recargos ni actualizaciones por pago extemporáneo (Art. 17-A CFF).
"""

from __future__ import annotations

from core.taxation.calculation import (
    CALCULATION_VERSION,
    DivergenceImpact,
    LineItem,
    TaxCalculation,
    empty_calculation,
)
from core.taxation.engine import compute_divergence, compute_taxes, customs_value
from core.taxation.money import CENTS, WORKING, CurrencyMismatchError, Money, zero
from core.taxation.rates import TaxRates

__all__ = [
    "CALCULATION_VERSION",
    "CENTS",
    "WORKING",
    "CurrencyMismatchError",
    "DivergenceImpact",
    "LineItem",
    "Money",
    "TaxCalculation",
    "TaxRates",
    "compute_divergence",
    "compute_taxes",
    "customs_value",
    "empty_calculation",
    "zero",
]
