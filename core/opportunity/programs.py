"""PROSEC y Regla 8ª: cuándo una tasa de programa es una oportunidad (ADR 0011).

El motor no conoce ninguna tasa de programa: las recibe como `OpcionDePrograma`,
cada una con su sector, su tasa, su fuente y su vigencia, ya filtradas por la
fecha de la operación. Quien las busca es `database/repositories/programas.py`.

TRES COSAS QUE ESTE MÓDULO NO HACE

1. **No elige el sector por el importador.** Una fracción puede estar en varios
   sectores PROSEC con tasas distintas, y la Regla 8ª tiene una fracción 9802
   por sector. Si no consta en qué sectores opera el importador, PROSEC sale
   SIN monto —con la lista de sectores posibles— y la Regla 8ª no se evalúa:
   ofrecerle a una mueblera la tasa del sector automotriz sería inventar.
2. **No suma alternativas.** PROSEC y Regla 8ª sobre la misma partida, o dos
   sectores, son caminos distintos al mismo ahorro: se ofrece el mejor y se
   mencionan los demás. `OpportunityReport.total_potential` toma el mayor por
   partida por la misma razón.
3. **No da por cumplidas las condiciones.** Todo sale `POTENTIAL` (§23).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from core.opportunity.engine import from_preferential_rate
from core.opportunity.kinds import OpportunityKind
from core.opportunity.types import Opportunity, build

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.taxation import Money, TaxRates

#: Los tipos que salen de un programa de fomento, en el orden en que se evalúan.
PROGRAMAS: tuple[OpportunityKind, ...] = (OpportunityKind.PROSEC, OpportunityKind.REGLA_8A)


class OpcionDePrograma(BaseModel):
    """Una tasa de programa vigente en la fecha de la operación, con su fuente."""

    model_config = ConfigDict(frozen=True)

    kind: OpportunityKind
    """`PROSEC` o `REGLA_8A`."""
    sector_code: str
    sector_name: str
    fraction_code: str
    """PROSEC: la fracción de la mercancía. Regla 8ª: la 9802.00.xx del sector."""
    igi_rate: Decimal
    """Como fracción (0.05, no 5), igual que `TaxRates.igi_rate`."""
    is_partial: bool = False
    scope_note: str | None = None
    source_ids: tuple[Any, ...] = ()
    data_origin: str = "OFFICIAL"
    """Una tasa `SYNTHETIC` hace simulada la oportunidad aunque el pedimento
    sea real (§33)."""


def _pct(tasa: Decimal) -> str:
    return f"{(tasa * 100).normalize():f} %"


def _sector(opcion: OpcionDePrograma) -> str:
    return f"sector {opcion.sector_code} «{opcion.sector_name}»"


def _condiciones_extra(opcion: OpcionDePrograma) -> tuple[str, ...]:
    if opcion.kind is OpportunityKind.PROSEC and opcion.is_partial:
        return (f"Que la mercancía esté dentro de la acotación del decreto: {opcion.scope_note}",)
    if opcion.kind is OpportunityKind.REGLA_8A and opcion.scope_note:
        return (f"Que la mercancía no esté entre las exclusiones del sector: {opcion.scope_note}",)
    return ()


def from_programs(
    *,
    line_number: int,
    fraction_code: str | None,
    opciones: Sequence[OpcionDePrograma],
    transaction_value: Money | None,
    applied_rates: TaxRates | None,
    client_sectors: frozenset[str] | None,
    is_simulation: bool = True,
) -> list[Opportunity]:
    """Las oportunidades de programa de una partida: como mucho una por tipo.

    Sólo cuenta una opción si su tasa es MENOR que la aplicada. Sin tasa
    aplicada no se sabe si hay ahorro y no se devuelve nada: quien llama lo
    declara en las notas del informe.
    """
    if applied_rates is None:
        return []

    oportunidades: list[Opportunity] = []
    for kind in PROGRAMAS:
        mejores = sorted(
            (o for o in opciones if o.kind is kind and o.igi_rate < applied_rates.igi_rate),
            key=lambda o: (o.igi_rate, o.sector_code),
        )
        if not mejores:
            continue

        simulada = is_simulation or any(o.data_origin == "SYNTHETIC" for o in mejores)

        if client_sectors is None:
            # Sin saber el sector del importador, la Regla 8ª no se evalúa: hay
            # una 9802 por sector y cualquier elección sería inventada. PROSEC
            # sí se puede SEÑALAR —la fracción está en el decreto— pero no
            # cuantificar.
            if kind is OpportunityKind.PROSEC:
                oportunidades.append(
                    _sin_sector(line_number, fraction_code, applied_rates, mejores, simulada)
                )
            continue

        del_importador = [o for o in mejores if o.sector_code in client_sectors]
        if not del_importador:
            continue
        oportunidades.append(
            _cuantificada(
                line_number,
                fraction_code,
                del_importador,
                transaction_value=transaction_value,
                applied_rates=applied_rates,
                is_simulation=is_simulation
                or any(o.data_origin == "SYNTHETIC" for o in del_importador),
            )
        )
    return oportunidades


def _sin_sector(
    line_number: int,
    fraction_code: str | None,
    applied_rates: TaxRates,
    opciones: Sequence[OpcionDePrograma],
    is_simulation: bool,
) -> Opportunity:
    sectores = "; ".join(f"{_sector(o)} {_pct(o.igi_rate)}" for o in opciones)
    oportunidad = build(
        OpportunityKind.PROSEC,
        rationale=(
            f"La fracción {fraction_code} está en {len(opciones)} sector(es) del Decreto "
            f"PROSEC con arancel menor al aplicado ({_pct(applied_rates.igi_rate)}): "
            f"{sectores}. No consta en qué sector opera el importador, y sin eso no se "
            "cuantifica."
        ),
        line_number=line_number,
        fraction_code=fraction_code,
        source_ids=[s for o in opciones for s in o.source_ids],
        is_simulation=is_simulation,
    )
    extra = tuple(c for o in opciones for c in _condiciones_extra(o))
    return oportunidad.model_copy(update={"conditions": oportunidad.conditions + extra})


def _cuantificada(
    line_number: int,
    fraction_code: str | None,
    opciones: Sequence[OpcionDePrograma],
    *,
    transaction_value: Money | None,
    applied_rates: TaxRates,
    is_simulation: bool,
) -> Opportunity:
    mejor = opciones[0]
    via = (
        f"importándola por la fracción {mejor.fraction_code} de la Regla 8ª"
        if mejor.kind is OpportunityKind.REGLA_8A
        else "con la tasa del decreto PROSEC"
    )
    razon = (
        f"El importador opera en el {_sector(mejor)}: {via} el arancel sería "
        f"{_pct(mejor.igi_rate)} en vez de {_pct(applied_rates.igi_rate)}."
    )
    if mejor.is_partial:
        razon += " La fracción está acotada: sólo cubre parte de ella."
    if len(opciones) > 1:
        otros = ", ".join(_sector(o) for o in opciones[1:])
        razon += f" También aplicaría por: {otros}; no se suman, son alternativas."

    if transaction_value is None:
        oportunidad = build(
            mejor.kind,
            rationale=razon + " Sin valor en aduana no se cuantifica.",
            line_number=line_number,
            fraction_code=fraction_code,
            source_ids=mejor.source_ids,
            is_simulation=is_simulation,
        )
    else:
        oportunidad = from_preferential_rate(
            kind=mejor.kind,
            transaction_value=transaction_value,
            applied_rates=applied_rates,
            preferential_rates=applied_rates.model_copy(
                update={"igi_rate": mejor.igi_rate, "source_ids": mejor.source_ids}
            ),
            rationale=razon,
            line_number=line_number,
            fraction_code=fraction_code,
            is_simulation=is_simulation,
        )
    return oportunidad.model_copy(
        update={"conditions": oportunidad.conditions + _condiciones_extra(mejor)}
    )
