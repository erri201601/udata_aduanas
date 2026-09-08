"""Tipos de oportunidad y qué hace falta para confirmar cada una.

LA ASIMETRÍA QUE DEFINE ESTE MÓDULO

Un hallazgo de riesgo se puede afirmar: la fracción declarada no coincide con
la esperada, y eso es comprobable desde los datos. Una oportunidad NO.

Que una fracción esté en un sector PROSEC no significa que el importador pueda
usarlo — hace falta que esté inscrito en ese programa, y eso no está en ninguna
tabla nuestra. Que exista un tratado con el país de origen no significa que
aplique — hace falta el certificado de origen del embarque concreto.

Por eso cada tipo declara sus CONDICIONES: lo que alguien tiene que verificar
fuera del sistema antes de que la oportunidad deje de ser una hipótesis. El
§23 lo dice sin matices: `POTENTIAL` nunca se presenta como ahorro garantizado.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class OpportunityKind(StrEnum):
    """De dónde saldría el ahorro."""

    OVERPAYMENT = "OVERPAYMENT"
    """Se pagó de más sobre lo que correspondía.

    El único tipo que el sistema puede cuantificar por sí solo: sale de comparar
    lo declarado con lo esperado. Aun así la recuperación no es automática —hay
    plazos y un procedimiento— y por eso tampoco nace VALIDATED.
    """

    PROSEC = "PROSEC"
    """La fracción pertenece a un sector con tasa preferencial de PROSEC."""

    REGLA_8A = "REGLA_8A"
    """La mercancía podría importarse al amparo de la Regla 8ª.

    Permite clasificar componentes bajo una sola fracción cuando se destinan a
    la industria autorizada.
    """

    TRADE_PREFERENCE = "TRADE_PREFERENCE"
    """Existe preferencia arancelaria por el país de origen."""

    CORRECTION = "CORRECTION"
    """Una rectificación permitida que reduciría lo pagado, distinta de un
    sobrepago simple."""


#: Qué hay que verificar FUERA del sistema para que deje de ser hipótesis.
#:
#: Estas condiciones no son advertencias legales genéricas: son la lista de
#: cosas concretas que alguien tiene que ir a comprobar. Sin ellas, una
#: oportunidad es un número bonito que nadie sabe si puede cobrar.
CONDITIONS: Final[dict[OpportunityKind, tuple[str, ...]]] = {
    OpportunityKind.OVERPAYMENT: (
        "Que el plazo para solicitar la devolución siga abierto.",
        "Que el pedimento no esté sujeto a un procedimiento en curso.",
    ),
    OpportunityKind.PROSEC: (
        "Que el importador esté inscrito en el programa PROSEC del sector.",
        "Que la mercancía se destine al proceso productivo que ampara el programa.",
        "Que el registro estuviera vigente en la fecha de la operación.",
    ),
    OpportunityKind.REGLA_8A: (
        "Que exista autorización vigente para aplicar la Regla 8ª.",
        "Que la mercancía forme parte de un bien de la industria autorizada.",
    ),
    OpportunityKind.TRADE_PREFERENCE: (
        "Que exista certificado de origen válido para el embarque.",
        "Que la mercancía cumpla la regla de origen específica de la fracción.",
        "Que el tratado estuviera vigente en la fecha de la operación.",
    ),
    OpportunityKind.CORRECTION: (
        "Que la rectificación proceda conforme a la Ley Aduanera.",
        "Que no se haya iniciado el ejercicio de facultades de comprobación.",
    ),
}

#: Tipos que el sistema puede cuantificar sin datos externos.
#:
#: Los demás necesitan la tasa preferencial del programa o tratado, que viene
#: de fuera. Sin ella se reporta la oportunidad sin monto, que es honesto: es
#: mejor decir "aquí puede haber algo" que inventar cuánto.
SELF_QUANTIFIABLE: Final[frozenset[OpportunityKind]] = frozenset({OpportunityKind.OVERPAYMENT})
