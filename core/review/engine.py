"""Encadena los cuatro motores sobre un pedimento completo.

    Espejo → Money Finder → Audit → Opportunity

POR QUÉ LA AUDITORÍA VA POR PARTIDA Y NO POR PEDIMENTO

`core.audit.audit()` recibe UN valor y UN par de tasas, porque calcula UNA
diferencia de contribuciones. Eso es correcto para una partida: dentro de ella,
una fracción equivocada y un valor equivocado explican el mismo delta, y por
eso `_total()` toma el máximo y no la suma.

Entre partidas distintas es al revés: son mercancías distintas, con valores y
tasas distintas, y su dinero SÍ se suma. Así que aquí se audita línea por
línea y se suman los totales de cada informe. Auditar el pedimento entero de
una vez daría el delta de una sola partida presentado como si fuera el del
pedimento.

QUÉ PASA CON LAS DIVISAS

Si las partidas vienen en divisas distintas no se suman: el total queda en
`None` y `mixed_currencies` dice por qué. Convertirlas exigiría elegir un tipo
de cambio, y elegirlo mal cambia la cifra que se le lleva al cliente.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from core.audit import AuditReport, Finding, audit
from core.opportunity import find_opportunities
from core.review.types import LineInput, PedimentoReview
from core.shadow import ExpectedItem, ShadowComparison, compare

if TYPE_CHECKING:
    from collections.abc import Sequence

REVIEW_VERSION = "review-1.0"


def review_pedimento(
    lines: Sequence[LineInput],
    *,
    sku_history: dict[str, str] | None = None,
) -> PedimentoReview:
    """Revisa un pedimento completo. No toca la base ni llama a ningún modelo."""
    declaradas = [ln.declared for ln in lines]
    esperadas: list[ExpectedItem] = [ln.expected for ln in lines if ln.expected is not None]

    # Una sola comparación para todo el pedimento: la consistencia histórica
    # del SKU sólo se ve mirando las partidas juntas.
    comparacion = compare(declaradas, esperadas, sku_history=sku_history)

    hallazgos: list[Finding] = []
    exposiciones: list[Decimal] = []
    recuperables: list[Decimal] = []
    divisas: set[str] = set()

    por_linea = {ln.declared.line_number: ln for ln in lines}

    for numero, entrada in por_linea.items():
        propias = tuple(d for d in comparacion.divergences if d.line_number == numero)
        if not propias:
            continue

        informe = audit(
            # Sólo las divergencias de esta partida: el monto que calcule tiene
            # que corresponder a la mercancía cuyas tasas se le están pasando.
            ShadowComparison(divergences=propias),
            transaction_value=entrada.transaction_value,
            declared_rates=entrada.declared_rates,
            expected_rates=entrada.expected_rates,
            is_simulation=entrada.is_simulation,
        )
        hallazgos.extend(informe.findings)

        if informe.total_exposure is not None:
            exposiciones.append(informe.total_exposure)
        if informe.total_recoverable is not None:
            recuperables.append(informe.total_recoverable)
        if informe.currency is not None:
            divisas.add(informe.currency)

    mezcladas = len(divisas) > 1
    divisa = next(iter(divisas)) if len(divisas) == 1 else None

    total_exposicion = sum(exposiciones, Decimal(0)) if exposiciones and not mezcladas else None
    total_recuperable = sum(recuperables, Decimal(0)) if recuperables and not mezcladas else None

    # Una simulación en cualquier partida contamina el informe: si parte de lo
    # que se auditó es sintético, el resultado no puede presentarse como real
    # (§33). Basta una para que todo se marque.
    es_simulacion = any(ln.is_simulation for ln in lines) if lines else True

    # El informe consolidado se ARMA con lo que ya se calculó por partida; no se
    # vuelve a auditar. Reauditar la comparación completa sin las tasas de cada
    # línea daría hallazgos sin monto, y entonces el buscador de oportunidades
    # no vería ni un sobrepago: los sobrepagos se detectan justamente por el
    # signo del monto.
    consolidado = AuditReport(
        findings=tuple(hallazgos),
        unverifiable=comparacion.unverifiable,
        total_exposure=total_exposicion,
        total_recoverable=total_recuperable,
        currency=divisa,
        is_simulation=es_simulacion,
    )

    oportunidades = find_opportunities(
        audit=consolidado if hallazgos else None,
        currency=divisa,
        is_simulation=es_simulacion,
    )

    return PedimentoReview(
        comparison=comparacion,
        findings=tuple(hallazgos),
        opportunities=oportunidades,
        total_exposure=total_exposicion,
        total_recoverable=total_recuperable,
        currency=divisa,
        mixed_currencies=mezcladas,
        is_simulation=es_simulacion,
    )
