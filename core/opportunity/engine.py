"""Busca ahorros que el importador pudo aprovechar y no aprovechó.

Es el reverso del Audit Engine. Aquél busca lo que se pagó de menos —riesgo—;
éste, lo que se pudo pagar de menos legítimamente y no se hizo.

POR QUÉ NO PUEDE AFIRMAR NADA

El Audit Engine compara dos cosas que están en los datos: lo declarado y lo
esperado. Aquí no. Que una fracción esté en un sector PROSEC no dice si el
importador está inscrito; que exista un tratado con China no dice si hay
certificado de origen de este embarque. Esos hechos viven fuera del sistema.

Así que el motor detecta la POSIBILIDAD y enumera lo que falta comprobar. El
§23 es explícito: `POTENTIAL` nunca se presenta como ahorro garantizado.

Y como el resto de motores, no conoce ninguna tasa preferencial: las recibe.
Inventar que PROSEC deja el IGI en 5% sería inventar fundamento jurídico.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.opportunity.kinds import OpportunityKind
from core.opportunity.types import Opportunity, OpportunityReport, build
from core.taxation import compute_taxes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.audit import AuditReport
    from core.taxation import Money, TaxRates


def from_audit(report: AuditReport) -> list[Opportunity]:
    """Convierte los sobrepagos que el Audit Engine ya detectó.

    Es el único tipo que el sistema cuantifica solo: sale de comparar lo
    declarado con lo esperado, y las dos cifras están en los datos.

    Aun así nace `POTENTIAL`. Que se pagó de más es un hecho; que se pueda
    recuperar depende de plazos y de que no haya un procedimiento en curso, y
    eso el motor no lo sabe.
    """
    return [
        build(
            OpportunityKind.OVERPAYMENT,
            rationale=(
                f"Se pagaron {abs(f.impact_amount):,.2f} {f.impact_currency} de más "  # type: ignore[arg-type]
                f"por {f.divergence.kind.value.lower().replace('_', ' ')} en la línea "
                f"{f.divergence.line_number}."
            ),
            line_number=f.divergence.line_number,
            # En valor absoluto. El Audit Engine guarda el sobrepago como
            # NEGATIVO —es `esperado - declarado`, y en un sobrepago lo
            # esperado es menor—, pero un ahorro es siempre una magnitud
            # positiva: la dirección ya la dice el hecho de ser una
            # oportunidad y no un riesgo. Sumar un negativo con el ahorro
            # positivo de una tasa preferencial los cancelaría, y el total
            # saldría en cero con dos oportunidades reales sobre la mesa.
            estimated_saving=abs(f.impact_amount),
            currency=f.impact_currency,
            source_ids=f.divergence.source_ids,
            is_simulation=f.is_simulation,
        )
        for f in report.findings
        if f.is_opportunity and f.impact_amount is not None
    ]


def from_preferential_rate(
    *,
    kind: OpportunityKind,
    transaction_value: Money,
    applied_rates: TaxRates,
    preferential_rates: TaxRates,
    rationale: str,
    line_number: int | None = None,
    fraction_code: str | None = None,
    incrementables: Sequence[Money] = (),
    is_simulation: bool = True,
) -> Opportunity:
    """Cuantifica el ahorro de una tasa preferencial frente a la aplicada.

    Quien llama aporta `preferential_rates` —del programa PROSEC, del tratado,
    de la Regla 8ª— porque esas tasas son datos jurídicos con vigencia y fuente.
    El motor no las conoce ni las supone.

    Si la preferencial no ahorra nada, devuelve la oportunidad SIN monto en vez
    de una cifra negativa: «podrías pagar más» no es una oportunidad, y un
    número con signo raro en un informe es lo que hace que dejen de leerlo.
    """
    actual = compute_taxes(
        transaction_value=transaction_value,
        rates=applied_rates,
        incrementables=incrementables,
        is_simulation=is_simulation,
    )
    preferente = compute_taxes(
        transaction_value=transaction_value,
        rates=preferential_rates,
        incrementables=incrementables,
        is_simulation=is_simulation,
    )
    ahorro = actual.total_taxes - preferente.total_taxes

    return build(
        kind,
        rationale=rationale,
        line_number=line_number,
        fraction_code=fraction_code,
        estimated_saving=ahorro.amount if ahorro.amount > 0 else None,
        currency=ahorro.currency if ahorro.amount > 0 else None,
        source_ids=preferential_rates.source_ids,
        is_simulation=is_simulation,
    )


def find_opportunities(
    *,
    audit: AuditReport | None = None,
    extra: Sequence[Opportunity] = (),
    currency: str | None = None,
    is_simulation: bool = True,
) -> OpportunityReport:
    """Reúne las oportunidades de una operación.

    `extra` son las que el llamante ya cuantificó con `from_preferential_rate`,
    porque requieren datos que el motor no tiene: qué sectores PROSEC aplican a
    la fracción, qué tratados cubren el origen. Cuando esos catálogos existan
    —hoy no están cargados— esto los consultará directamente.
    """
    oportunidades: list[Opportunity] = []
    notas: list[str] = []

    if audit is not None:
        oportunidades.extend(from_audit(audit))
    else:
        notas.append("Sin informe de auditoría: no se buscaron sobrepagos.")

    oportunidades.extend(extra)

    if not any(o.kind is not OpportunityKind.OVERPAYMENT for o in oportunidades):
        notas.append(
            "PROSEC, Regla 8ª y preferencias arancelarias no se evaluaron: sus "
            "catálogos no están cargados. Que no aparezcan aquí NO significa que "
            "no existan."
        )

    divisa = currency or next((o.currency for o in oportunidades if o.currency is not None), None)

    return OpportunityReport(
        opportunities=tuple(oportunidades),
        currency=divisa,
        is_simulation=is_simulation or any(o.is_simulation for o in oportunidades),
        notes=tuple(notas),
    )
