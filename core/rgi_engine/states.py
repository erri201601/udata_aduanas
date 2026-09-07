"""Estados de una evaluación RGI.

Cuatro estados, y sólo tres pueden persistirse. `CONTINUE` es interno de la
máquina: significa "esta regla no resolvió, pasa a la siguiente", y si llegara
a una `ClassificationDecision` sería un error — Brandon definió el vocabulario
persistible en `database/models/enums.py::CLASSIFICATION_STATUS` con tres
valores, y esa asimetría es deliberada.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class RGIStatus(StrEnum):
    """Con qué termina la evaluación de una regla."""

    RESOLVED = "RESOLVED"
    """La regla determinó la clasificación. La secuencia se detiene."""

    CONTINUE = "CONTINUE"
    """La regla no aplica o no basta. Pasa a la siguiente.

    Estado interno de la máquina: NUNCA se persiste como resultado final.
    """

    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    """Falta información del producto para poder decidir.

    No es un fallo del motor: es el motor negándose a inventar. El §8.2 del
    maestro lo exige explícitamente. Lo que falta va en `missing_information`,
    y es accionable — se le puede pedir al importador.
    """

    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    """Hay información suficiente pero la decisión excede lo que el motor puede
    sostener por sí solo.

    Casos típicos: dos candidatos igual de defendibles, o una regla cuyas
    precondiciones se cumplen pero que esta versión aún no implementa. Escalar
    es la respuesta correcta; adivinar, no.
    """


#: Estados con los que la secuencia se detiene. `CONTINUE` no está.
TERMINAL: Final[frozenset[RGIStatus]] = frozenset(
    {
        RGIStatus.RESOLVED,
        RGIStatus.INSUFFICIENT_INFORMATION,
        RGIStatus.HUMAN_REVIEW_REQUIRED,
    }
)
