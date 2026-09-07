"""Ajuste de severidad según el impacto económico.

El Pedimento Espejo asigna severidad por TIPO de divergencia: una fracción
equivocada es CRITICAL porque cambia el arancel. Pero ese juicio no distingue
entre una fracción equivocada de mil pesos y una de un millón, y para quien
decide qué revisar primero esa diferencia lo es todo.

LA REGLA: el tipo pone el suelo, el dinero puede subirlo. Nunca lo baja.

Un NOM faltante detiene la mercancía valga lo que valga; rebajarlo porque el
monto es pequeño sería confundir «barato» con «leve». Y una omisión de
contribuciones no deja de ser una infracción porque sea de poco dinero.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

#: De menor a mayor. El orden permite subir un escalón.
ESCALA: Final[tuple[str, ...]] = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")

#: Umbrales de monto, de mayor a menor, con la severidad MÍNIMA que imponen.
#:
#: Son un punto de partida calibrable, NO una verdad jurídica: no salen de
#: ninguna norma. Viven aquí y no repartidos por el código para que cambiarlos
#: sea una decisión visible, y cada hallazgo los declara como supuesto.
UMBRALES: Final[tuple[tuple[Decimal, str], ...]] = (
    (Decimal("500000"), "CRITICAL"),
    (Decimal("100000"), "HIGH"),
    (Decimal("10000"), "MEDIUM"),
    (Decimal("1000"), "LOW"),
)


def severity_for_amount(amount: Decimal) -> str:
    """Severidad mínima que impone un monto por sí solo."""
    magnitud = abs(amount)
    for umbral, nivel in UMBRALES:
        if magnitud >= umbral:
            return nivel
    return "INFO"


def adjust(base: str, *, amount: Decimal | None) -> tuple[str, str | None]:
    """Ajusta la severidad de una divergencia con su impacto.

    Devuelve `(severidad, motivo)`. El motivo es `None` si no hubo ajuste, y
    viaja al hallazgo: una severidad que subió sin explicación es una decisión
    que nadie puede revisar.
    """
    if amount is None or amount == 0:
        return base, None

    por_monto = severity_for_amount(amount)
    if ESCALA.index(por_monto) <= ESCALA.index(base):
        return base, None

    return por_monto, (
        f"Severidad elevada de {base} a {por_monto} por un impacto de {abs(amount):,.2f}."
    )
