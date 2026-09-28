"""Cuánto se puede fiar uno de un porcentaje, dado cuántos casos lo respaldan.

Un 100 % sobre un caso y un 100 % sobre ochenta se leen igual y no valen igual.
El intervalo de Wilson pone esa diferencia en el reporte: con un caso el margen
sale tan ancho que el número se descalifica solo, sin que nadie tenga que
recordar la n.

Vive aparte porque lo usan las DOS métricas del §26 —detección y hs_accuracy—
y una segunda copia se desincroniza el día que alguien la toque.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Final

#: 95 % de confianza.
Z: Final = 1.96

_CIEN: Final = Decimal(100)
_DOS: Final = Decimal("0.01")


def wilson(exitos: int, total: int) -> Decimal | None:
    """Media anchura del intervalo de Wilson, en puntos porcentuales.

    `None` sin casos: desconocido, que no es lo mismo que cero.

    Se usa Wilson y no la aproximación normal porque con pocos casos —o con
    proporciones pegadas a 0 o a 100— la normal da intervalos que se salen del
    rango o que se encogen a nada. Justo los dos casos en los que más falta
    hace no engañarse.
    """
    if total <= 0:
        return None
    p = exitos / total
    denominador = 1 + Z**2 / total
    mitad = Z * math.sqrt(p * (1 - p) / total + Z**2 / (4 * total**2)) / denominador
    return (Decimal(mitad) * _CIEN).quantize(_DOS)
