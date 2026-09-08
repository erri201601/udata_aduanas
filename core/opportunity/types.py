"""La oportunidad: un ahorro posible, con lo que falta por comprobar.

`status` nace siempre en `POTENTIAL`. Pasa a `VALIDATED` cuando un humano
confirma las condiciones, y a `REJECTED` cuando descubre que no se cumplen. El
motor no puede hacer ninguna de las dos transiciones: no tiene forma de saber
si el importador está inscrito en PROSEC.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from core.opportunity.kinds import CONDITIONS, OpportunityKind

if TYPE_CHECKING:
    from collections.abc import Sequence


class Opportunity(BaseModel):
    """Un ahorro que podría existir. Todavía no consta que exista."""

    model_config = ConfigDict(frozen=True)

    kind: OpportunityKind
    status: str = "POTENTIAL"
    """POTENTIAL | VALIDATED | REJECTED. Nace POTENTIAL, siempre."""

    line_number: int | None = None
    fraction_code: str | None = None
    rationale: str = ""

    estimated_saving: Decimal | None = None
    """`None` cuando el sistema no tiene con qué calcularlo — porque falta la
    tasa preferencial del programa o del tratado. Es honesto: mejor decir
    «aquí puede haber algo» que inventar cuánto."""

    currency: str | None = None
    conditions: tuple[str, ...] = ()
    """Lo que alguien tiene que verificar fuera del sistema. Sin esto, una
    oportunidad es un número que nadie sabe si puede cobrar."""

    source_ids: tuple[Any, ...] = ()
    is_simulation: bool = True

    @property
    def is_quantified(self) -> bool:
        return self.estimated_saving is not None and self.estimated_saving != 0

    @property
    def is_actionable(self) -> bool:
        """¿Se le puede llevar a un cliente?

        Sólo si además de existir se sabe cuánto vale. «Podrías ahorrar algo»
        no mueve a nadie a revisar un pedimento.
        """
        return self.is_quantified

    def to_finding_fields(self) -> dict[str, Any]:
        """Mapeo plano hacia `intelligence.opportunity_findings` (§29)."""
        return {
            "opportunity_type": self.kind.value,
            "status": self.status,
            "rationale": self._rationale(),
            "estimated_saving_amount": self.estimated_saving,
            "estimated_saving_amount_currency": self.currency,
        }

    def _rationale(self) -> str:
        """El razonamiento CON sus condiciones.

        Van juntos a propósito: quien lea la fila en la base tiene que ver que
        es una hipótesis, no sólo quien mire la pantalla. Separarlos permitiría
        que un informe cite el monto sin las condiciones.
        """
        partes = [self.rationale] if self.rationale else []
        if self.conditions:
            partes.append("Por verificar: " + " · ".join(self.conditions))
        return " ".join(partes)

    def explain(self) -> str:
        cabecera = f"[{self.status}] {self.kind.value}"
        if self.line_number is not None:
            cabecera += f" · línea {self.line_number}"
        lineas = [cabecera, f"  {self.rationale}"]
        if self.is_quantified:
            marca = " (simulado)" if self.is_simulation else ""
            lineas.append(
                f"  Ahorro estimado: {abs(self.estimated_saving):,.2f} "  # type: ignore[arg-type]
                f"{self.currency}{marca}"
            )
        else:
            lineas.append("  Ahorro: no cuantificado — falta la tasa preferencial.")
        lineas += [f"  · {c}" for c in self.conditions]
        return "\n".join(lineas)


class OpportunityReport(BaseModel):
    """Las oportunidades encontradas en una operación."""

    model_config = ConfigDict(frozen=True)

    opportunities: tuple[Opportunity, ...] = ()
    currency: str | None = None
    is_simulation: bool = True
    notes: tuple[str, ...] = Field(default_factory=tuple)
    """Lo que no se pudo evaluar, y por qué. Igual que en el Espejo: «no
    encontré oportunidades» y «no pude buscarlas» son cosas distintas."""

    @property
    def total_potential(self) -> Decimal | None:
        """Suma de lo cuantificado. NO es dinero prometido.

        Cada sumando es una hipótesis con condiciones propias, así que el total
        es «el techo si todas se confirman», no un pronóstico. Presentarlo
        como ahorro esperado sería lo que el §23 prohíbe, y a mayor escala:
        un total suena más firme que cada parte.
        """
        # La condición se escribe entera y no `if o.is_quantified` porque una
        # property no estrecha el Optional para el verificador de tipos, y sumar
        # una lista que puede contener None es justo el error que evita.
        montos = [
            o.estimated_saving
            for o in self.opportunities
            if o.estimated_saving is not None and o.estimated_saving != 0
        ]
        return sum(montos, Decimal("0")) if montos else None

    @property
    def actionable(self) -> tuple[Opportunity, ...]:
        return tuple(o for o in self.opportunities if o.is_actionable)

    def by_kind(self, kind: OpportunityKind) -> tuple[Opportunity, ...]:
        return tuple(o for o in self.opportunities if o.kind is kind)

    def summary(self) -> str:
        if not self.opportunities:
            base = "Sin oportunidades detectadas."
            return f"{base} {' '.join(self.notes)}" if self.notes else base
        marca = " (simulado)" if self.is_simulation else ""
        lineas = [f"{len(self.opportunities)} oportunidad(es) POTENCIAL(es)."]
        total = self.total_potential
        if total:
            lineas.append(
                f"Techo si todas se confirman: {abs(total):,.2f} "
                f"{self.currency}{marca}. Ninguna está confirmada todavía."
            )
        sin_monto = len(self.opportunities) - len(self.actionable)
        if sin_monto:
            lineas.append(f"{sin_monto} sin cuantificar por falta de tasa preferencial.")
        if self.notes:
            lineas += list(self.notes)
        return "\n".join(lineas)


def build(
    kind: OpportunityKind,
    *,
    rationale: str,
    line_number: int | None = None,
    fraction_code: str | None = None,
    estimated_saving: Decimal | None = None,
    currency: str | None = None,
    source_ids: Sequence[Any] = (),
    is_simulation: bool = True,
) -> Opportunity:
    """Construye una oportunidad con las condiciones de su tipo ya puestas.

    No hay forma de crear una sin ellas: es lo que impide que una oportunidad
    salga del sistema pareciendo un hecho.
    """
    return Opportunity(
        kind=kind,
        status="POTENTIAL",
        line_number=line_number,
        fraction_code=fraction_code,
        rationale=rationale,
        estimated_saving=estimated_saving,
        currency=currency,
        conditions=CONDITIONS[kind],
        source_ids=tuple(source_ids),
        is_simulation=is_simulation,
    )
