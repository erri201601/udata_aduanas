"""De dónde salen los casos de evaluación.

Un puerto y no un lector concreto porque el formato todavía no existe: Persona 2
hace el reconocimiento de CBP CROSS. Cuando llegue, su adaptador implementa
esto y el harness no cambia (§29).

LO QUE UN ADAPTADOR TIENE PROHIBIDO

Convertir una clasificación que no es del SA 2022 en un HS6, o derivar el HS6
de una fracción mexicana. Un HTS10 de Estados Unidos NUNCA se traduce a TIGIE:
se toman sus seis primeros dígitos —que son el SA— y se declara la
nomenclatura. Si el ruling no es del SA 2022, se entrega con su nomenclatura
real y el harness lo excluye; no se «ajusta».
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator

    from core.evaluation.harness import CasoDeEvaluacion


@runtime_checkable
class FuenteDeCasos(Protocol):
    """Entrega casos con verdad conocida, uno a uno."""

    nombre: str
    """«CBP_CROSS». Viaja al reporte: un número sin fuente no se puede auditar."""

    def casos(self) -> Iterator[CasoDeEvaluacion]:
        """Los casos, en orden estable. Mismo orden en cada corrida."""
        ...
