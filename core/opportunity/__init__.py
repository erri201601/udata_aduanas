"""Opportunity Finder — lo que se pudo ahorrar y no se aprovechó.

Es el reverso del Audit Engine. Aquél busca lo que se pagó de menos —riesgo—;
éste, lo que se pudo pagar de menos legítimamente y no se hizo.

USO

    from core.opportunity import find_opportunities, from_preferential_rate

    informe = find_opportunities(audit=informe_de_auditoria)

    informe.opportunities       # todas, siempre POTENTIAL
    informe.actionable          # las que además tienen monto
    informe.total_potential     # el techo si TODAS se confirman
    informe.summary()

    # Cuando se conoce la tasa de un programa:
    prosec = from_preferential_rate(
        kind=OpportunityKind.PROSEC,
        transaction_value=valor,
        applied_rates=tasas_aplicadas,
        preferential_rates=tasas_prosec,   # con su fuente y vigencia
        rationale="La fracción pertenece al sector electrónico de PROSEC.",
    )

LA ASIMETRÍA QUE DEFINE ESTE MÓDULO

Un hallazgo de riesgo se puede afirmar: la fracción declarada no coincide con
la esperada, y las dos cifras están en los datos. Una oportunidad NO.

Que una fracción esté en un sector PROSEC no dice si el importador está
inscrito. Que exista un tratado con el país de origen no dice si hay
certificado para este embarque. Esos hechos viven fuera del sistema.

Por eso todo nace `POTENTIAL` y **no hay forma de construir una oportunidad sin
sus condiciones**: la lista concreta de lo que alguien tiene que ir a comprobar.
Sin ellas, una oportunidad es un número que nadie sabe si puede cobrar.

`total_potential` es el techo si todas se confirman, no un pronóstico.
Presentarlo como ahorro esperado sería lo que el §23 prohíbe, y a mayor escala:
un total suena más firme que cada parte.

QUÉ NO HACE

No conoce ninguna tasa preferencial: las recibe, igual que el RGI recibe la
tarifa. Inventar que PROSEC deja el IGI en 5% sería inventar fundamento
jurídico.

No valida ni rechaza: `POTENTIAL` → `VALIDATED` sólo lo mueve un humano que
confirmó las condiciones, y eso vive en la interfaz de revisión.

PENDIENTE

PROSEC, Regla 8ª y las preferencias por tratado no se evalúan solas: sus
catálogos no están cargados. El informe lo DECLARA en `notes` — que no
aparezcan no significa que no existan.
"""

from __future__ import annotations

from core.opportunity.engine import (
    find_opportunities,
    from_audit,
    from_preferential_rate,
)
from core.opportunity.kinds import CONDITIONS, SELF_QUANTIFIABLE, OpportunityKind
from core.opportunity.types import Opportunity, OpportunityReport, build

__all__ = [
    "CONDITIONS",
    "SELF_QUANTIFIABLE",
    "Opportunity",
    "OpportunityKind",
    "OpportunityReport",
    "build",
    "find_opportunities",
    "from_audit",
    "from_preferential_rate",
]
