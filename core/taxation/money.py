"""Dinero, con la divisa pegada al importe.

§22 del maestro: `Decimal`, nunca `float`. Un `float` no puede representar 0.1
de forma exacta, y en un cálculo de contribuciones los errores se acumulan
hasta producir un peso de diferencia — que en un pedimento es una
discrepancia, no un redondeo.

La divisa va dentro del tipo, no al lado. Sumar 100 USD y 100 MXN debe ser un
error del programa, no un 200 sin unidades. El modelo de Persona 2 ya lo hace
así en la base (`<campo>` + `<campo>_currency`); esto es lo mismo en memoria.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

#: Precisión de trabajo. NUMERIC(18,6) en la base, así que seis decimales.
#: Los cálculos intermedios NO se redondean a dos: redondear antes de tiempo
#: mete error en cada paso en vez de sólo en el resultado.
WORKING = Decimal("0.000001")

#: Precisión de presentación y de lo que se declara en el pedimento.
CENTS = Decimal("0.01")


class CurrencyMismatchError(Exception):
    """Se intentó operar con dos divisas distintas.

    No se convierte automáticamente a propósito: una conversión necesita un
    tipo de cambio con fecha y fuente (el FIX de Banxico del día), y elegirlo
    en silencio es inventar un dato que cambia el resultado.
    """

    def __init__(self, a: str, b: str) -> None:
        super().__init__(
            f"No se puede operar {a} con {b} sin un tipo de cambio explícito. "
            f"Usa Money.convert() con la tasa y su fecha."
        )


class Money(BaseModel):
    """Un importe con su divisa. Inmutable."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: str

    @field_validator("amount", mode="before")
    @classmethod
    def _a_decimal(cls, v: Any) -> Decimal:
        """Rechaza `float` en la entrada.

        Aceptar un `float` "por comodidad" es cómo entra el error de precisión:
        `Decimal(0.1)` ya vale 0.1000000000000000055511151231257827. Si el dato
        viene de fuera, que llegue como cadena o Decimal.
        """
        if isinstance(v, float):
            raise TypeError(
                "El dinero no se construye desde float (§22). Usa Decimal o str: "
                f"Money(amount=Decimal('{v}'), ...)"
            )
        return Decimal(v) if not isinstance(v, Decimal) else v

    @field_validator("currency")
    @classmethod
    def _iso(cls, v: str) -> str:
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"La divisa debe ser un código ISO de 3 letras, no {v!r}")
        return v.upper()

    # ── Operaciones ──────────────────────────────────────────────────────────

    def _misma_divisa(self, otro: Money) -> None:
        if self.currency != otro.currency:
            raise CurrencyMismatchError(self.currency, otro.currency)

    def __add__(self, otro: Money) -> Money:
        self._misma_divisa(otro)
        return Money(amount=self.amount + otro.amount, currency=self.currency)

    def __sub__(self, otro: Money) -> Money:
        self._misma_divisa(otro)
        return Money(amount=self.amount - otro.amount, currency=self.currency)

    def __mul__(self, tasa: Decimal) -> Money:
        """Multiplica por una tasa. `float` prohibido, igual que en el constructor."""
        if isinstance(tasa, float):
            raise TypeError("Las tasas son Decimal, nunca float (§22).")
        return Money(
            amount=(self.amount * Decimal(tasa)).quantize(WORKING, rounding=ROUND_HALF_UP),
            currency=self.currency,
        )

    def __neg__(self) -> Money:
        return Money(amount=-self.amount, currency=self.currency)

    def __lt__(self, otro: Money) -> bool:
        self._misma_divisa(otro)
        return self.amount < otro.amount

    def quantize(self, exp: Decimal = CENTS) -> Money:
        """Redondea a la precisión dada, media hacia arriba.

        ROUND_HALF_UP y no el banquero de Python por defecto: es la convención
        fiscal, y `ROUND_HALF_EVEN` haría que 0.125 → 0.12, que a un auditor le
        parece un centavo perdido.
        """
        return Money(
            amount=self.amount.quantize(exp, rounding=ROUND_HALF_UP), currency=self.currency
        )

    def convert(self, *, to: str, rate: Decimal) -> Money:
        """Convierte con un tipo de cambio explícito.

        Quien llame es responsable de que `rate` sea el vigente en la fecha de
        la operación —el FIX de Banxico del día hábil anterior, para pedimentos—
        y de registrarlo como evidencia. Este método no lo busca ni lo supone.
        """
        if isinstance(rate, float):
            raise TypeError("El tipo de cambio es Decimal, nunca float (§22).")
        return Money(
            amount=(self.amount * Decimal(rate)).quantize(WORKING, rounding=ROUND_HALF_UP),
            currency=to.upper(),
        )

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def __str__(self) -> str:
        return f"{self.quantize().amount:,.2f} {self.currency}"


def zero(currency: str) -> Money:
    """Cero en una divisa concreta. Punto de partida de las sumas."""
    return Money(amount=Decimal("0"), currency=currency)
