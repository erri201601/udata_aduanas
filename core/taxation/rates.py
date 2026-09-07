"""Las tasas y cuotas que entran al cálculo.

EL MOTOR NO CONOCE NINGUNA TASA. Las recibe.

Es la misma decisión que en el RGI Engine, y por el mismo motivo: una tasa
arancelaria es un dato jurídico con vigencia y fuente. Codificar «IGI 15%» aquí
sería inventar fundamento (§8.1) y, peor, congelarlo — el día que cambie en el
DOF, el sistema seguiría calculando con la anterior sin que nadie lo note.

Las tasas vienen de `regulatory.tariff_fractions` (Persona 2), con su
`valid_from`/`valid_to`, y quien las obtiene debe emitir la evidencia
`LEGAL_SOURCE` que las respalda.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class TaxRates(BaseModel):
    """Tasas aplicables a una operación concreta, en una fecha concreta.

    Todas son fracciones, no porcentajes: 0.16 y no 16. Mezclar las dos
    convenciones es un error de dos órdenes de magnitud, y en un cálculo de
    contribuciones eso es la diferencia entre un pedimento correcto y una
    multa.
    """

    model_config = ConfigDict(frozen=True)

    igi_rate: Decimal = Decimal("0")
    """Impuesto General de Importación, ad valorem. Sale de la fracción."""

    iva_rate: Decimal = Decimal("0")
    """IVA. 0.16 general, 0.08 en región fronteriza, 0 en exentos."""

    dta_rate: Decimal = Decimal("0")
    """Derecho de Trámite Aduanero, ad valorem (el «8 al millar» = 0.008)."""

    dta_fixed: Decimal | None = None
    """Cuota fija de DTA, cuando el régimen la usa en vez de la tasa."""

    ieps_rate: Decimal = Decimal("0")
    """IEPS, sólo en las mercancías que lo causan."""

    countervailing_rate: Decimal = Decimal("0")
    """Cuota compensatoria ad valorem (antidumping)."""

    prevalidation_fee: Decimal | None = None
    """Cuota fija de prevalidación."""

    source_ids: tuple[Any, ...] = ()
    """Fuentes que respaldan estas tasas. Sin esto el cálculo no se puede
    defender: un número sin origen no es un fundamento."""

    @field_validator(
        "igi_rate",
        "iva_rate",
        "dta_rate",
        "ieps_rate",
        "countervailing_rate",
        mode="before",
    )
    @classmethod
    def _fraccion_no_porcentaje(cls, v: Any) -> Decimal:
        """Rechaza `float` y atrapa el porcentaje escrito como entero.

        Una tasa mayor que 1 casi siempre es un 16 que debía ser 0.16. Prefiero
        fallar ruidoso a calcular un IVA del 1600%: el segundo error se detecta
        semanas después, cuando alguien mira un total absurdo.
        """
        if isinstance(v, float):
            raise TypeError("Las tasas son Decimal, nunca float (§22).")
        d = Decimal(v) if not isinstance(v, Decimal) else v
        if d < 0:
            raise ValueError(f"Una tasa no puede ser negativa: {d}")
        if d > 1:
            raise ValueError(
                f"La tasa {d} es mayor que 1. Las tasas van como fracción, no como "
                f"porcentaje: 0.16 y no 16."
            )
        return d

    @property
    def has_any(self) -> bool:
        """¿Hay alguna tasa distinta de cero?

        Todas en cero suele significar que no se cargaron, no que la mercancía
        esté exenta de todo. Quien llama debe distinguirlo.
        """
        return any(
            [
                self.igi_rate,
                self.iva_rate,
                self.dta_rate,
                self.ieps_rate,
                self.countervailing_rate,
                self.dta_fixed,
                self.prevalidation_fee,
            ]
        )
