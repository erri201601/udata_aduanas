"""Los dos lados de la comparación, y el resultado.

La idea entera del Pedimento Espejo (§9.3) es que el sistema construya lo que
DEBERÍA declararse sin mirar lo declarado, y sólo después compare. Si mirara
primero, tendería a justificar lo que ya está ahí — que es exactamente el sesgo
que un revisor humano tiene y que la máquina debería no tener.

Por eso `ExpectedItem` se construye desde el Product DNA y la clasificación, y
`DeclaredItem` desde el pedimento, sin que ninguno conozca al otro.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.shadow.divergences import DEFAULT_SEVERITY, DivergenceType


class DeclaredItem(BaseModel):
    """Una partida tal como viene en el pedimento.

    Todo es opcional salvo la línea: un pedimento incompleto es justamente uno
    de los hallazgos posibles, así que el tipo tiene que poder representarlo.
    """

    model_config = ConfigDict(frozen=True)

    line_number: int
    description: str | None = None
    fraction_code: str | None = None
    nico_code: str | None = None
    country_of_origin: str | None = None
    customs_value: Decimal | None = None
    customs_value_currency: str | None = None
    applied_nom_codes: tuple[str, ...] = ()
    identifiers: dict[str, Any] = Field(default_factory=dict)
    sku: str | None = None


class ExpectedItem(BaseModel):
    """Lo que el sistema esperaría ver, construido sin mirar lo declarado."""

    model_config = ConfigDict(frozen=True)

    line_number: int
    fraction_code: str | None = None
    nico_code: str | None = None
    country_of_origin: str | None = None
    customs_value: Decimal | None = None
    customs_value_currency: str | None = None
    required_nom_codes: tuple[str, ...] | None = None
    """Las NOM que la fracción exige. `None` significa QUE NO SE SABE.

    La distinción no es cosmética. Una tupla vacía afirma «esta fracción no
    exige ninguna NOM» y permite decir que el pedimento está limpio en ese
    campo; `None` dice «no tengo la fuente para saberlo» y manda la partida a
    `unverifiable`.

    El valor por omisión es `None` a propósito: hoy no existe la correlación
    fracción → NOM. No está en el Anexo 22 (verificado por Persona 2 el
    2026-09-08: el Apéndice 9 explica qué significa cada código, pero remite al
    Anexo 2.2.1 de un Acuerdo distinto de la Secretaría de Economía para saber
    qué fracciones lo exigen). Mientras esa fuente no esté cargada, quien
    construya un `ExpectedItem` sin tocar este campo obtiene «no sé», que es la
    verdad, en vez de «no exige ninguna», que sería inventar.
    """

    required_identifiers: tuple[str, ...] | None = None
    """Identificadores del Anexo 22 que la operación exige. `None` = no se sabe.

    Misma semántica que `required_nom_codes`. El Apéndice 8 del Anexo 22 —el
    catálogo de identificadores— está pendiente de cargar.
    """
    sku: str | None = None

    confidence: Decimal | None = None
    """Cuánta confianza tiene el sistema en lo que espera.

    Importa para no acusar con seguridad desde una base insegura: una
    divergencia contra una expectativa de confianza 0.4 no es un hallazgo, es
    una pregunta.
    """

    source_ids: tuple[Any, ...] = ()
    is_resolved: bool = False
    """`False` cuando la clasificación no llegó a ser defendible. Entonces no
    se puede afirmar que lo declarado esté mal: sólo que no se pudo verificar.
    """


class Divergence(BaseModel):
    """Una diferencia concreta entre lo declarado y lo esperado."""

    model_config = ConfigDict(frozen=True)

    kind: DivergenceType
    line_number: int
    field: str
    declared_value: str | None = None
    expected_value: str | None = None
    severity: str = "MEDIUM"
    confidence: Decimal | None = None
    reasoning: str = ""
    source_ids: tuple[Any, ...] = ()
    requires_human_review: bool = True

    def to_finding_fields(self) -> dict[str, Any]:
        """Mapeo plano hacia `intelligence.risk_findings`.

        `core/` no importa la persistencia (§29): quien escriba la fila
        ensambla, igual que en los otros motores.
        """
        return {
            "finding_type": self.kind.value,
            "field": self.field,
            "declared_value": self.declared_value,
            "expected_value": self.expected_value,
            "severity": self.severity,
            "confidence": self.confidence,
            "requires_human_review": self.requires_human_review,
            "reasoning": self.reasoning,
        }


class ShadowComparison(BaseModel):
    """El resultado de comparar un pedimento completo contra su espejo."""

    model_config = ConfigDict(frozen=True)

    divergences: tuple[Divergence, ...] = ()
    unverifiable: tuple[str, ...] = ()
    """Partidas que NO se pudieron verificar, con su razón.

    Se declaran aparte de las divergencias a propósito. «No encontré nada mal»
    y «no pude comprobarlo» son cosas distintas, y confundirlas haría que un
    pedimento sin verificar pareciera limpio (§36).
    """

    @property
    def has_findings(self) -> bool:
        return bool(self.divergences)

    @property
    def is_complete(self) -> bool:
        """¿Se pudo verificar todo?

        Un `True` aquí es lo que permite decir «este pedimento está limpio».
        Con `False`, lo más que se puede decir es «no encontré nada en lo que
        pude revisar».
        """
        return not self.unverifiable

    def by_severity(self, severity: str) -> tuple[Divergence, ...]:
        return tuple(d for d in self.divergences if d.severity == severity)

    @property
    def worst_severity(self) -> str | None:
        """La severidad más alta encontrada. Ordena la bandeja de revisión."""
        orden = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        presentes = {d.severity for d in self.divergences}
        return next((s for s in orden if s in presentes), None)

    def summary(self) -> str:
        """Resumen legible, para que un humano lo lea o un LLM lo narre."""
        if not self.divergences and self.is_complete:
            return "Sin divergencias. Se verificaron todas las partidas."
        if not self.divergences:
            return (
                f"Sin divergencias en lo verificable, pero {len(self.unverifiable)} "
                f"partida(s) no se pudieron comprobar: {'; '.join(self.unverifiable)}"
            )
        lineas = [f"{len(self.divergences)} divergencia(s), la más grave {self.worst_severity}:"]
        lineas += [
            f"  [{d.severity}] línea {d.line_number} · {d.field}: "
            f"declarado {d.declared_value!r} vs esperado {d.expected_value!r}"
            for d in self.divergences
        ]
        if self.unverifiable:
            lineas.append("No verificable: " + "; ".join(self.unverifiable))
        return "\n".join(lineas)


def default_severity(kind: DivergenceType) -> str:
    """Severidad por defecto del tipo de divergencia."""
    return DEFAULT_SEVERITY.get(kind, "MEDIUM")
