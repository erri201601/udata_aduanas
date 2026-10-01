"""El motor de auditoría: divergencias + dinero + evidencia = hallazgos.

    Pedimento Espejo  →  Money Finder  →  Evidence  →  Finding
       qué difiere       cuánto cuesta    con qué      accionable

Es lo que convierte «la fracción está mal» en «la fracción está mal y son
11,600 pesos omitidos, según la LIGIE vigente ese día». La primera frase se
ignora; la segunda se corrige.

CUÁNDO NO SE CUANTIFICA

Sólo las divergencias que cambian lo que se paga tienen impacto económico. Una
NOM faltante detiene la mercancía pero no altera las contribuciones, y un
identificador ausente tampoco. Inventarles un monto para que la tabla se vea
completa sería exactamente lo que el §36 prohíbe: un número plausible es peor
que un hueco declarado, porque el hueco se ve y el número no.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.audit.findings import AuditReport, Finding
from core.audit.severity import adjust
from core.shadow import DivergenceType
from core.taxation import compute_divergence, compute_taxes

if TYPE_CHECKING:
    from collections.abc import Sequence
    from decimal import Decimal

    from core.evidence import Evidence
    from core.shadow import Divergence, ShadowComparison
    from core.taxation import DivergenceImpact, Money, TaxRates

#: Divergencias que alteran lo que se paga. Sólo éstas se cuantifican.
#:
#: FRACTION y VALUE cambian la base o la tasa. ORIGIN puede cambiar la
#: preferencia arancelaria y con ella el arancel. Las demás importan por
#: cumplimiento, no por dinero.
CUANTIFICABLES: frozenset[DivergenceType] = frozenset(
    {
        DivergenceType.FRACTION_MISMATCH,
        DivergenceType.VALUE_MISMATCH,
        DivergenceType.ORIGIN_MISMATCH,
    }
)


def audit(
    comparison: ShadowComparison,
    *,
    transaction_value: Money | None = None,
    declared_rates: TaxRates | None = None,
    expected_rates: TaxRates | None = None,
    incrementables: Sequence[Money] = (),
    evidences: Sequence[Evidence] = (),
    is_simulation: bool = True,
) -> AuditReport:
    """Convierte una comparación del Espejo en hallazgos accionables.

    Sin `transaction_value` ni tasas, los hallazgos salen sin impacto: siguen
    siendo válidos como riesgo de cumplimiento, sólo que no cuantificados. Es
    un resultado honesto, no un fallo — y `is_actionable` lo distingue.
    """
    impacto = None
    supuestos: list[str] = []

    puede_cuantificar = (
        transaction_value is not None and declared_rates is not None and expected_rates is not None
    )

    if puede_cuantificar:
        declarado = compute_taxes(
            transaction_value=transaction_value,  # type: ignore[arg-type]
            rates=declared_rates,  # type: ignore[arg-type]
            incrementables=incrementables,
            is_simulation=is_simulation,
        )
        esperado = compute_taxes(
            transaction_value=transaction_value,  # type: ignore[arg-type]
            rates=expected_rates,  # type: ignore[arg-type]
            incrementables=incrementables,
            is_simulation=is_simulation,
        )
        impacto = compute_divergence(declared=declarado, expected=esperado)
        supuestos = list(esperado.assumptions)
    else:
        supuestos.append(
            "Sin tasas ni valor de transacción: los hallazgos van sin impacto "
            "económico. Son válidos como riesgo de cumplimiento, no cuantificados."
        )

    # El monto se atribuye ENTERO a cada divergencia cuantificable, no se
    # reparte. Repartirlo daría cifras que no cuadran con nada verificable: la
    # diferencia real de contribuciones es UNA, y cada causa la explica por
    # completo. `_total` se encarga de no contarla dos veces al sumar.
    hallazgos = [
        _a_hallazgo(
            d,
            impacto=impacto if (impacto and d.kind in CUANTIFICABLES) else None,
            evidences=evidences,
            supuestos=supuestos,
            is_simulation=is_simulation,
        )
        for d in comparison.divergences
    ]

    total_omitido = _total(hallazgos, "OMISION")
    total_recuperable = _total(hallazgos, "SOBREPAGO")

    return AuditReport(
        findings=tuple(hallazgos),
        unverifiable=comparison.unverifiable,
        verified=comparison.verified,
        total_exposure=total_omitido,
        total_recoverable=total_recuperable,
        currency=impacto.difference.currency if impacto else None,
        is_simulation=is_simulation or (impacto.is_simulation if impacto else True),
    )


def _a_hallazgo(
    divergencia: Divergence,
    *,
    impacto: DivergenceImpact | None,
    evidences: Sequence[Evidence],
    supuestos: Sequence[str],
    is_simulation: bool,
) -> Finding:
    """Convierte una divergencia en hallazgo, con su impacto si lo tiene."""
    monto: Decimal | None = None
    divisa: str | None = None
    direccion: str | None = None

    if impacto is not None:
        monto = impacto.difference.amount
        divisa = impacto.difference.currency
        direccion = impacto.direction

    severidad, motivo = adjust(divergencia.severity, amount=monto)

    return Finding(
        divergence=divergencia,
        severity=severidad,
        severity_reason=motivo,
        impact_amount=monto,
        impact_currency=divisa,
        impact_direction=direccion,
        evidences=tuple(evidences),
        assumptions=tuple(supuestos),
        is_simulation=is_simulation,
    )


def _total(hallazgos: Sequence[Finding], direccion: str) -> Decimal | None:
    """Total de una dirección, SIN duplicar.

    Varias divergencias pueden explicar la misma diferencia de contribuciones
    —una fracción equivocada y un valor equivocado producen un único delta—,
    así que sumar los montos de cada hallazgo contaría el mismo dinero dos
    veces. El total es el monto, no la suma.
    """
    montos = {
        f.impact_amount
        for f in hallazgos
        if f.impact_direction == direccion and f.impact_amount is not None
    }
    if not montos:
        return None
    return max(montos, key=abs)
