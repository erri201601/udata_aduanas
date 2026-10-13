"""`InvoiceGenerator` (§24 maestro): los montos de una partida limpia.

Fórmula verificada contra las 15 partidas sin anomalía fiscal del corpus ya
cargado (`PED_SIM_001`, partida 1; reproducida a mano, 13-oct-2026) -- no
inventada:

    valor_aduana_mxn = precio_pagado_mxn + incrementables_mxn
    dta_mxn          = round(valor_aduana_mxn * 0.008, 2)      # art. 49 LFD
    igi_mxn          = round(valor_aduana_mxn * igi_rate, 2)
    iva_base_mxn     = valor_aduana_mxn + igi_mxn + dta_mxn
    iva_mxn          = round(iva_base_mxn * iva_rate, 2)

Todo en `Decimal` (§22 maestro) -- nunca `float`. Este módulo no decide si
una partida está bien o mal: eso es `ErrorInjector`. Esto sólo calcula la
versión consistente, que luego el inyector muta donde el escenario lo pida.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_DTA_RATE = Decimal("0.008")
_CENTAVO = Decimal("0.01")


def _redondear(valor: Decimal) -> Decimal:
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MontosPartida:
    precio_pagado_mxn: Decimal
    incrementables_mxn: Decimal
    valor_aduana_mxn: Decimal
    dta_mxn: Decimal
    igi_mxn: Decimal
    iva_base_mxn: Decimal
    iva_mxn: Decimal
    igi_rate: Decimal
    iva_rate: Decimal


def calcular(
    *,
    precio_pagado_mxn: Decimal,
    incrementables_mxn: Decimal,
    igi_rate: Decimal,
    iva_rate: Decimal = Decimal("0.16"),
) -> MontosPartida:
    valor_aduana_mxn = precio_pagado_mxn + incrementables_mxn
    dta_mxn = _redondear(valor_aduana_mxn * _DTA_RATE)
    igi_mxn = _redondear(valor_aduana_mxn * igi_rate)
    iva_base_mxn = valor_aduana_mxn + igi_mxn + dta_mxn
    iva_mxn = _redondear(iva_base_mxn * iva_rate)
    return MontosPartida(
        precio_pagado_mxn=precio_pagado_mxn,
        incrementables_mxn=incrementables_mxn,
        valor_aduana_mxn=valor_aduana_mxn,
        dta_mxn=dta_mxn,
        igi_mxn=igi_mxn,
        iva_base_mxn=iva_base_mxn,
        iva_mxn=iva_mxn,
        igi_rate=igi_rate,
        iva_rate=iva_rate,
    )
