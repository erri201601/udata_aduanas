"""El resultado de clasificar un producto, con todo lo que lo sostiene.

Reúne lo que producen los cuatro motores: la traza del RGI, la evidencia que la
respalda, el impacto económico y las diez respuestas del §49. Es lo que se
persiste y lo que se enseña en la Evidence UI.

`core/` no importa la capa de persistencia (§29): esto son tipos de dominio y
`to_decision_fields()` devuelve un dict plano. Quien escriba la fila ensambla.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from core.evidence import Dossier, Evidence
from core.rgi_engine import ClassificationTrace, RGIStatus
from core.taxation import DivergenceImpact

if TYPE_CHECKING:
    from decimal import Decimal


class ClassificationOutcome(BaseModel):
    """Clasificación completa de un producto, defendible por sí sola."""

    model_config = ConfigDict(frozen=True)

    trace: ClassificationTrace
    """Qué reglas se evaluaron, en qué orden y con qué resultado."""

    operation_date: date
    """La fecha con la que se evaluó. Se conserva porque todo lo que venga
    después —cuantificar, rehacer el dossier— la necesita, y reconstruirla a
    partir de las evidencias sería adivinar."""

    evidences: tuple[Evidence, ...] = ()
    dossier: Dossier | None = None
    """Las diez preguntas del §49. `None` si no se pudo ensamblar."""

    impact: DivergenceImpact | None = None
    """Impacto económico frente a lo declarado. `None` si no había con qué
    comparar — clasificar un producto no siempre implica un pedimento."""

    blocked_by: str | None = None
    """Por qué no se pudo sostener la clasificación, si es el caso.

    Se llena cuando el contrato de evidencia rechaza el resultado: la
    clasificación existía pero no era defendible, que no es lo mismo que no
    haber clasificado.
    """

    facts_used: dict[str, str] = Field(default_factory=dict)

    @property
    def status(self) -> RGIStatus:
        return self.trace.final_status

    @property
    def code(self) -> str | None:
        """La fracción, sólo si es defendible.

        Un código que el contrato de evidencia rechazó NO se devuelve. Es la
        diferencia entre "el motor llegó a 8471.30.01" y "8471.30.01 es
        defendible", y sólo la segunda sirve para declarar un pedimento.
        """
        return None if self.blocked_by else self.trace.resolved_code

    @property
    def confidence(self) -> Decimal | None:
        return self.trace.confidence

    @property
    def requires_human_review(self) -> bool:
        """Cualquier duda sobre la clasificación escala.

        NO incluye que el dossier esté incompleto. Un dossier al que le falta
        `money_impact` porque no hay pedimento contra el que comparar describe
        una clasificación perfectamente sólida: clasificar un producto sin
        operación declarada es un caso legítimo, no una duda.

        Escalar por eso saturaría la bandeja de revisión con casos correctos, y
        una bandeja saturada se deja de mirar — que es peor que no tenerla.
        `dossier.is_complete` sigue disponible aparte para quien lo necesite.
        """
        return self.blocked_by is not None or self.trace.requires_human_review

    def to_decision_fields(self) -> dict[str, Any]:
        """Mapeo plano hacia `intelligence.classification_decisions`.

        `evidence_id` no viaja aquí: es el id de una fila que aún no existe
        cuando el orquestador termina. Lo pone quien persiste, igual que hace
        Persona 3 con los atributos.
        """
        return {
            "status": self.status.value,
            "fraction_code": self.code,
            "reasoning": " · ".join(
                p.reasoning_summary for p in self.trace.steps if p.reasoning_summary
            ),
            "rgi_path": [p.rule_id for p in self.trace.steps],
            "engine_version": self.trace.engine_version,
            "confidence": self.confidence,
            "requires_human_review": self.requires_human_review,
            "missing_information": list(self.trace.missing_information),
        }

    def explain(self) -> str:
        """El caso completo en texto, para que un LLM lo narre o un humano lo lea.

        Nunca para que un modelo lo recalcule: los números ya vienen resueltos
        del Money Finder (§22).
        """
        lineas = [f"Estado: {self.status.value}"]
        if self.code:
            lineas.append(f"Fracción: {self.code}")
        if self.blocked_by:
            lineas.append(f"NO DEFENDIBLE: {self.blocked_by}")
        lineas += [f"  {p.rule_id}: {p.reasoning_summary}" for p in self.trace.steps]
        if self.trace.missing_information:
            lineas.append("Falta: " + ", ".join(self.trace.missing_information))
        if self.impact is not None:
            lineas.append(f"Impacto: {self.impact.as_money_impact()}")
        if self.requires_human_review:
            lineas.append("REQUIERE REVISIÓN HUMANA")
        return "\n".join(lineas)
