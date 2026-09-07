"""El resultado de un cálculo, con todo lo que hace falta para defenderlo.

§22 del maestro exige que toda salida monetaria exponga: formula, inputs,
result, currency, calculation_version, assumptions, source_ids, is_simulation.

El motivo de tanto campo es concreto. Un número solo —«son 12,450 pesos»— no se
puede auditar ni reproducir. Con la fórmula y las entradas, cualquiera repite
el cálculo a mano y llega al mismo sitio, que es lo que un agente aduanal
necesita para firmar.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.taxation.money import Money, zero

CALCULATION_VERSION = "0.1.0"


class LineItem(BaseModel):
    """Una contribución concreta, con cómo se obtuvo."""

    model_config = ConfigDict(frozen=True)

    concept: str
    """IGI · DTA · IVA · IEPS · CUOTA_COMPENSATORIA · PREVALIDACION"""

    formula: str
    """La fórmula legible: 'valor_aduana × 0.15'. Es lo que permite repetir el
    cálculo a mano."""

    inputs: dict[str, str] = Field(default_factory=dict)
    """Las entradas exactas, como cadenas para no perder precisión al
    serializar."""

    amount: Money
    rate: Decimal | None = None
    source_ids: tuple[Any, ...] = ()


class TaxCalculation(BaseModel):
    """El cálculo completo de las contribuciones de una operación."""

    model_config = ConfigDict(frozen=True)

    customs_value: Money
    """Valor en aduana: base de casi todo lo demás."""

    items: tuple[LineItem, ...] = ()
    total_taxes: Money
    landed_cost: Money
    """Valor en aduana + contribuciones. Lo que de verdad cuesta la mercancía
    puesta en el país."""

    calculation_version: str = CALCULATION_VERSION
    assumptions: tuple[str, ...] = ()
    """Lo que se dio por supuesto. Un cálculo con supuestos no declarados
    parece más firme de lo que es (§36)."""

    source_ids: tuple[Any, ...] = ()
    is_simulation: bool = True
    """`True` si alguna entrada es SYNTHETIC. Por defecto sí: mientras no
    conste que los datos son reales, el resultado es una simulación y se
    presenta como tal (§10, §33)."""

    def item(self, concept: str) -> LineItem | None:
        """Busca una contribución por concepto."""
        return next((i for i in self.items if i.concept == concept), None)

    def explain(self) -> str:
        """El cálculo en texto plano, línea por línea.

        Esto es lo que un LLM puede *explicar* — nunca calcular (§22). Se le da
        ya resuelto y lo pone en palabras.
        """
        lineas = [f"Valor en aduana: {self.customs_value}"]
        lineas += [f"  {i.concept}: {i.formula} = {i.amount}" for i in self.items]
        lineas.append(f"Total de contribuciones: {self.total_taxes}")
        lineas.append(f"Costo puesto en el país: {self.landed_cost}")
        if self.assumptions:
            lineas.append("Supuestos: " + " · ".join(self.assumptions))
        if self.is_simulation:
            lineas.append("SIMULACIÓN — alguna entrada es SYNTHETIC.")
        return "\n".join(lineas)


class DivergenceImpact(BaseModel):
    """Cuánto dinero representa una divergencia entre lo declarado y lo esperado.

    Es lo que convierte un hallazgo en algo accionable. Nadie rectifica un
    pedimento por una discrepancia abstracta; lo rectifica cuando ve el número.

    Responde la novena pregunta del §49: ¿cuánto dinero representa?
    """

    model_config = ConfigDict(frozen=True)

    declared: TaxCalculation
    expected: TaxCalculation
    difference: Money
    """Positivo = se pagó de menos (omisión). Negativo = se pagó de más
    (sobrepago, y por tanto una oportunidad de recuperación)."""

    by_concept: dict[str, str] = Field(default_factory=dict)
    """Diferencia por contribución, para saber de dónde sale el total."""

    is_simulation: bool = True

    @property
    def is_underpayment(self) -> bool:
        """¿Se pagó de menos? Es riesgo: omisión de contribuciones."""
        return self.difference.amount > 0

    @property
    def is_overpayment(self) -> bool:
        """¿Se pagó de más? Es oportunidad, y puede ser recuperable."""
        return self.difference.amount < 0

    @property
    def direction(self) -> str:
        if self.is_underpayment:
            return "OMISION"
        if self.is_overpayment:
            return "SOBREPAGO"
        return "SIN_DIFERENCIA"

    def as_money_impact(self) -> str:
        """Cadena para `Dossier.money_impact` del Evidence Contract.

        Deja explícito que es simulación cuando lo es: un número presentado sin
        esa marca se lee como real, y los datos operativos del MVP son
        sintéticos (§33).
        """
        signo = {"OMISION": "omitidos", "SOBREPAGO": "pagados de más"}.get(
            self.direction, "sin diferencia"
        )
        base = f"{abs(self.difference.amount):,.2f} {self.difference.currency} {signo}"
        return f"{base} (simulado)" if self.is_simulation else base


def empty_calculation(currency: str) -> TaxCalculation:
    """Un cálculo en cero. Punto de partida y caso degenerado."""
    z = zero(currency)
    return TaxCalculation(customs_value=z, total_taxes=z, landed_cost=z)
