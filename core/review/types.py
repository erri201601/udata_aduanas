"""Entradas y salida de una revisión completa de pedimento."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from core.audit import Finding
from core.opportunity import OpportunityReport
from core.shadow import DeclaredItem, ExpectedItem, ShadowComparison
from core.taxation import Money, TaxRates


class LineInput(BaseModel):
    """Una partida lista para revisar: lo declarado, lo esperado y sus tasas.

    `expected` es `None` cuando no se pudo construir una expectativa —la
    partida no tiene producto ligado, o su Product DNA no alcanzó para
    clasificar—. No se sustituye por un `ExpectedItem` vacío: eso haría que la
    partida se compare contra nada y salga limpia (§36).
    """

    model_config = ConfigDict(frozen=True)

    declared: DeclaredItem
    expected: ExpectedItem | None = None

    transaction_value: Money | None = None
    """Base gravable de esta partida. Sin ella el hallazgo existe pero no se
    cuantifica."""

    declared_rates: TaxRates | None = None
    """Tasas de la fracción DECLARADA."""

    expected_rates: TaxRates | None = None
    """Tasas de la fracción ESPERADA. La diferencia contra las declaradas es
    justamente el dinero."""

    is_simulation: bool = True


class PedimentoReview(BaseModel):
    """El resultado de revisar un pedimento de punta a punta."""

    model_config = ConfigDict(frozen=True)

    comparison: ShadowComparison
    findings: tuple[Finding, ...] = ()
    opportunities: OpportunityReport | None = None

    total_exposure: Decimal | None = None
    """Suma de lo omitido en TODAS las partidas."""

    total_recoverable: Decimal | None = None
    currency: str | None = None

    mixed_currencies: bool = False
    """Hubo partidas en divisas distintas y NO se sumaron.

    Sumar importes de divisas distintas daría una cifra sin significado. Se
    prefiere no dar total a dar uno falso — y decir por qué.
    """

    is_simulation: bool = True

    @property
    def is_complete(self) -> bool:
        """¿Se revisó todo? Sólo con `True` se puede decir «este pedimento está
        limpio»."""
        return self.comparison.is_complete

    @property
    def unverifiable(self) -> tuple[str, ...]:
        return self.comparison.unverifiable

    @property
    def worst_severity(self) -> str | None:
        orden = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
        presentes = {f.severity for f in self.findings}
        return next((s for s in orden if s in presentes), None)

    def summary(self) -> str:
        """Una línea para la bandeja de revisión."""
        if not self.findings and self.is_complete:
            return "Sin hallazgos. Se revisaron todas las partidas."
        if not self.findings:
            return (
                f"Sin hallazgos en lo revisable, pero {len(self.unverifiable)} "
                f"punto(s) quedaron sin comprobar."
            )
        cabeza = f"{len(self.findings)} hallazgo(s), el más grave {self.worst_severity}"

        if self.mixed_currencies:
            return (
                f"{cabeza}. Sin total: las partidas vienen en divisas distintas "
                f"y sumarlas daría una cifra sin significado."
            )

        # El sobrepago se guarda con signo negativo —así lo produce el Money
        # Finder—, pero al leerlo se habla de cuánto se puede recuperar, no de
        # menos diecisiete mil.
        partes: list[str] = []
        if self.total_exposure is not None:
            partes.append(f"exposición estimada {self.total_exposure} {self.currency}")
        if self.total_recoverable is not None:
            partes.append(f"recuperable {abs(self.total_recoverable)} {self.currency}")

        if not partes:
            return f"{cabeza}. Sin cuantificar: faltan valor o tasas."
        # Sólo la primera letra: `.capitalize()` bajaría "MXN" a "mxn".
        texto = ", ".join(partes)
        return f"{cabeza}. {texto[0].upper()}{texto[1:]}."
