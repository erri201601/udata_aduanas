"""El cálculo determinista de contribuciones.

§22 del maestro: los cálculos monetarios se hacen con código. NUNCA se le pide
a un modelo que calcule el IGI, el IVA o los recargos. Un modelo puede explicar
un resultado ya calculado; no puede producirlo, porque no hay forma de auditar
una aritmética que salió de una red neuronal.

EL ORDEN DE LAS CONTRIBUCIONES NO ES ARBITRARIO

    valor en aduana = valor de transacción + incrementables
    IGI   = valor en aduana × tasa
    DTA   = valor en aduana × tasa   (o cuota fija)
    IEPS  = (valor en aduana + IGI) × tasa
    IVA   = (valor en aduana + IGI + DTA + IEPS + cuotas) × tasa

El IVA se causa sobre el valor en aduana MÁS las demás contribuciones, no sobre
el valor en aduana solo. Calcularlo sobre la base equivocada da un número
menor, plausible, y equivocado — el peor tipo de error, porque nadie lo
cuestiona hasta que llega una revisión.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.taxation.calculation import (
    CALCULATION_VERSION,
    DivergenceImpact,
    LineItem,
    TaxCalculation,
)
from core.taxation.money import CENTS, Money, zero

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.taxation.rates import TaxRates


def customs_value(
    *,
    transaction_value: Money,
    incrementables: Sequence[Money] = (),
) -> tuple[Money, list[str]]:
    """Valor en aduana = valor de transacción + incrementables.

    Los incrementables son fletes, seguros, embalajes y demás gastos hasta el
    punto de entrada al país. Omitirlos subvalúa la mercancía y arrastra el
    error a todas las contribuciones, porque todas se calculan sobre esta base.

    Devuelve también los supuestos: si no vienen incrementables, eso se declara
    en vez de darlo por bueno en silencio.
    """
    total = transaction_value
    for inc in incrementables:
        total = total + inc

    supuestos: list[str] = []
    if not incrementables:
        supuestos.append(
            "No se recibieron incrementables (flete, seguro, embalaje). Si la "
            "operación los tuvo, el valor en aduana está subvaluado y todas las "
            "contribuciones salen bajas."
        )
    return total.quantize(CENTS), supuestos


def compute_taxes(
    *,
    transaction_value: Money,
    rates: TaxRates,
    incrementables: Sequence[Money] = (),
    is_simulation: bool = True,
    extra_source_ids: Sequence[Any] = (),
) -> TaxCalculation:
    """Calcula las contribuciones de una operación de importación.

    `is_simulation` viene en `True` por defecto: mientras no conste que los
    datos son reales, el resultado es una simulación y se presenta como tal
    (§10 y §33). Los datos operativos del MVP son sintéticos.
    """
    ccy = transaction_value.currency
    base, supuestos = customs_value(
        transaction_value=transaction_value, incrementables=incrementables
    )
    items: list[LineItem] = []

    if not rates.has_any:
        supuestos.append(
            "Todas las tasas llegaron en cero. Puede ser una mercancía exenta, "
            "pero también que las tasas no se hayan cargado: no es lo mismo y "
            "conviene verificarlo antes de usar este cálculo."
        )

    # ── IGI ──────────────────────────────────────────────────────────────────
    igi = base * rates.igi_rate
    items.append(
        LineItem(
            concept="IGI",
            formula=f"valor_aduana({base.amount}) × {rates.igi_rate}",
            inputs={"valor_aduana": str(base.amount), "tasa": str(rates.igi_rate)},
            amount=igi.quantize(CENTS),
            rate=rates.igi_rate,
            source_ids=tuple(rates.source_ids),
        )
    )

    # ── DTA ──────────────────────────────────────────────────────────────────
    if rates.dta_fixed is not None:
        dta = Money(amount=rates.dta_fixed, currency=ccy)
        formula_dta = f"cuota fija({rates.dta_fixed})"
        entradas_dta = {"cuota_fija": str(rates.dta_fixed)}
    else:
        dta = base * rates.dta_rate
        formula_dta = f"valor_aduana({base.amount}) × {rates.dta_rate}"
        entradas_dta = {"valor_aduana": str(base.amount), "tasa": str(rates.dta_rate)}
    items.append(
        LineItem(
            concept="DTA",
            formula=formula_dta,
            inputs=entradas_dta,
            amount=dta.quantize(CENTS),
            rate=rates.dta_rate if rates.dta_fixed is None else None,
            source_ids=tuple(rates.source_ids),
        )
    )

    # ── Cuota compensatoria ──────────────────────────────────────────────────
    compensatoria = base * rates.countervailing_rate
    if not compensatoria.is_zero:
        items.append(
            LineItem(
                concept="CUOTA_COMPENSATORIA",
                formula=f"valor_aduana({base.amount}) × {rates.countervailing_rate}",
                inputs={
                    "valor_aduana": str(base.amount),
                    "tasa": str(rates.countervailing_rate),
                },
                amount=compensatoria.quantize(CENTS),
                rate=rates.countervailing_rate,
                source_ids=tuple(rates.source_ids),
            )
        )

    # ── IEPS: sobre valor en aduana + IGI ────────────────────────────────────
    ieps = zero(ccy)
    if rates.ieps_rate:
        base_ieps = base + igi
        ieps = base_ieps * rates.ieps_rate
        items.append(
            LineItem(
                concept="IEPS",
                formula=f"(valor_aduana + IGI)({base_ieps.amount}) × {rates.ieps_rate}",
                inputs={"base": str(base_ieps.amount), "tasa": str(rates.ieps_rate)},
                amount=ieps.quantize(CENTS),
                rate=rates.ieps_rate,
                source_ids=tuple(rates.source_ids),
            )
        )

    # ── Prevalidación ────────────────────────────────────────────────────────
    prevalidacion = zero(ccy)
    if rates.prevalidation_fee is not None:
        prevalidacion = Money(amount=rates.prevalidation_fee, currency=ccy)
        items.append(
            LineItem(
                concept="PREVALIDACION",
                formula=f"cuota fija({rates.prevalidation_fee})",
                inputs={"cuota_fija": str(rates.prevalidation_fee)},
                amount=prevalidacion.quantize(CENTS),
                source_ids=tuple(rates.source_ids),
            )
        )

    # ── IVA: sobre el valor en aduana MÁS las demás contribuciones ───────────
    base_iva = base + igi + dta + compensatoria + ieps + prevalidacion
    iva = base_iva * rates.iva_rate
    items.append(
        LineItem(
            concept="IVA",
            formula=(
                f"(valor_aduana + IGI + DTA + cuotas + IEPS + prevalidación)"
                f"({base_iva.amount}) × {rates.iva_rate}"
            ),
            inputs={"base_iva": str(base_iva.amount), "tasa": str(rates.iva_rate)},
            amount=iva.quantize(CENTS),
            rate=rates.iva_rate,
            source_ids=tuple(rates.source_ids),
        )
    )

    total = zero(ccy)
    for i in items:
        total = total + i.amount

    supuestos.append(
        "Redondeo a dos decimales por contribución, media hacia arriba. Las "
        "reglas exactas de redondeo del pedimento están en el Anexo 22 y no se "
        "han contrastado: NEEDS_VALIDATION."
    )

    return TaxCalculation(
        customs_value=base,
        items=tuple(items),
        total_taxes=total.quantize(CENTS),
        landed_cost=(base + total).quantize(CENTS),
        calculation_version=CALCULATION_VERSION,
        assumptions=tuple(supuestos),
        source_ids=(*rates.source_ids, *extra_source_ids),
        is_simulation=is_simulation,
    )


def compute_divergence(*, declared: TaxCalculation, expected: TaxCalculation) -> DivergenceImpact:
    """Cuánto dinero representa la diferencia entre lo declarado y lo esperado.

    Es lo que hace accionable un hallazgo del Pedimento Espejo y responde la
    novena pregunta del §49.

    El signo importa y no es simétrico en sus consecuencias: pagar de menos es
    una omisión de contribuciones —riesgo— y pagar de más es un sobrepago
    —oportunidad de recuperación—. Son dos conversaciones distintas con el
    cliente.
    """
    diferencia = expected.total_taxes - declared.total_taxes

    por_concepto: dict[str, str] = {}
    conceptos = {i.concept for i in (*declared.items, *expected.items)}
    for c in sorted(conceptos):
        d = declared.item(c)
        e = expected.item(c)
        monto_d = d.amount.amount if d else Decimal("0")
        monto_e = e.amount.amount if e else Decimal("0")
        delta = monto_e - monto_d
        if delta != 0:
            por_concepto[c] = str(delta)

    return DivergenceImpact(
        declared=declared,
        expected=expected,
        difference=diferencia.quantize(CENTS),
        by_concept=por_concepto,
        # Basta con que UNA de las dos sea simulación para que el resultado lo
        # sea: mezclar un cálculo real con uno sintético no produce un dato real.
        is_simulation=declared.is_simulation or expected.is_simulation,
    )
