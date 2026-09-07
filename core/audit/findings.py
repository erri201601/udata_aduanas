"""El hallazgo: una divergencia con su impacto y su evidencia.

Una divergencia dice QUÉ difiere. Un hallazgo dice además CUÁNTO CUESTA y CON
QUÉ SE SOSTIENE — y esa diferencia es la que decide si alguien lo corrige.

Nadie rectifica un pedimento por una discrepancia abstracta. Lo rectifica
cuando ve el número, y sólo si el número viene respaldado.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from core.evidence import Evidence
from core.shadow import Divergence


class Finding(BaseModel):
    """Un hallazgo de auditoría, listo para persistirse y para presentarse."""

    model_config = ConfigDict(frozen=True)

    divergence: Divergence
    severity: str
    """La del tipo, posiblemente elevada por el monto."""

    severity_reason: str | None = None
    """Por qué subió, si subió. Una severidad ajustada sin explicación es una
    decisión que nadie puede revisar."""

    impact_amount: Decimal | None = None
    impact_currency: str | None = None
    impact_direction: str | None = None
    """OMISION | SOBREPAGO | SIN_DIFERENCIA."""

    evidences: tuple[Evidence, ...] = ()
    assumptions: tuple[str, ...] = ()
    is_simulation: bool = True
    """§33: mientras alguna entrada sea SYNTHETIC, el hallazgo es una
    simulación y se presenta como tal."""

    @property
    def is_actionable(self) -> bool:
        """¿Se puede llevar a un cliente?

        Un hallazgo sin impacto cuantificado se puede investigar, pero no
        presentar: «tu fracción podría estar mal» no es accionable.
        `requires_human_review` no lo impide — se presenta con esa advertencia.
        """
        return self.impact_amount is not None and self.impact_amount != 0

    @property
    def is_opportunity(self) -> bool:
        """¿Es dinero recuperable en vez de riesgo?

        Un sobrepago es otra conversación con el cliente: no «tienes un
        problema» sino «pagaste de más». El Opportunity Finder lo recoge.
        """
        return self.impact_direction == "SOBREPAGO"

    def to_finding_fields(self) -> dict[str, Any]:
        """Mapeo plano hacia `intelligence.risk_findings`.

        `core/` no importa la persistencia (§29). Los ids de pedimento y de
        decisión no viajan aquí: los pone quien persiste, que es quien los
        tiene.
        """
        campos = self.divergence.to_finding_fields()
        campos.update(
            {
                "severity": self.severity,
                "rationale": self._rationale(),
                "impact_amount": self.impact_amount,
                "impact_amount_currency": self.impact_currency,
                "is_simulation": self.is_simulation,
            }
        )
        return campos

    def _rationale(self) -> str:
        partes = [self.divergence.reasoning]
        if self.severity_reason:
            partes.append(self.severity_reason)
        if self.assumptions:
            partes.append("Supuestos: " + " · ".join(self.assumptions))
        return " ".join(p for p in partes if p)

    def explain(self) -> str:
        """El hallazgo en texto, para un humano o para que un LLM lo narre.

        Los números vienen ya calculados del Money Finder: el modelo los
        explica, no los produce (§22).
        """
        d = self.divergence
        lineas = [
            f"[{self.severity}] línea {d.line_number} · {d.field}",
            f"  declarado: {d.declared_value!r}   esperado: {d.expected_value!r}",
            f"  {d.reasoning}",
        ]
        if self.impact_amount is not None:
            signo = {"OMISION": "omitidos", "SOBREPAGO": "pagados de más"}.get(
                self.impact_direction or "", ""
            )
            marca = " (simulado)" if self.is_simulation else ""
            lineas.append(
                f"  Impacto: {abs(self.impact_amount):,.2f} {self.impact_currency} {signo}{marca}"
            )
        else:
            lineas.append("  Impacto: no cuantificado — sin tasas para calcularlo.")
        if self.severity_reason:
            lineas.append(f"  {self.severity_reason}")
        return "\n".join(lineas)


class AuditReport(BaseModel):
    """El resultado de auditar un pedimento completo."""

    model_config = ConfigDict(frozen=True)

    findings: tuple[Finding, ...] = ()
    unverifiable: tuple[str, ...] = ()
    """Lo que no se pudo comprobar, heredado del Espejo.

    Va aparte de los hallazgos por la misma razón de siempre: «no encontré
    nada» y «no pude revisarlo» son cosas distintas, y confundirlas haría que
    un pedimento sin auditar pareciera limpio (§36).
    """

    total_exposure: Decimal | None = None
    """Suma de lo omitido. Es la cifra de la que se habla con el cliente."""

    total_recoverable: Decimal | None = None
    """Suma de lo pagado de más. Dinero potencialmente recuperable."""

    currency: str | None = None
    is_simulation: bool = True

    @property
    def is_complete(self) -> bool:
        """¿Se auditó todo? Sólo con `True` se puede decir «este pedimento está
        limpio»."""
        return not self.unverifiable

    @property
    def worst_severity(self) -> str | None:
        orden = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        presentes = {f.severity for f in self.findings}
        return next((s for s in orden if s in presentes), None)

    def by_severity(self, severity: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == severity)

    @property
    def opportunities(self) -> tuple[Finding, ...]:
        """Los sobrepagos. Otra conversación con el cliente."""
        return tuple(f for f in self.findings if f.is_opportunity)

    def summary(self) -> str:
        if not self.findings and self.is_complete:
            return "Sin hallazgos. Se auditaron todas las partidas."
        if not self.findings:
            return (
                f"Sin hallazgos en lo auditable, pero {len(self.unverifiable)} "
                f"partida(s) no se pudieron comprobar."
            )
        marca = " (simulado)" if self.is_simulation else ""
        lineas = [f"{len(self.findings)} hallazgo(s), el más grave {self.worst_severity}."]
        if self.total_exposure:
            lineas.append(
                f"Contribuciones omitidas: {self.total_exposure:,.2f} {self.currency}{marca}"
            )
        if self.total_recoverable:
            lineas.append(
                f"Pagado de más, potencialmente recuperable: "
                f"{abs(self.total_recoverable):,.2f} {self.currency}{marca}"
            )
        if self.unverifiable:
            lineas.append(f"No verificable: {len(self.unverifiable)} partida(s).")
        return "\n".join(lineas)


def empty_report(currency: str | None = None) -> AuditReport:
    """Informe vacío. Punto de partida."""
    return AuditReport(currency=currency)
