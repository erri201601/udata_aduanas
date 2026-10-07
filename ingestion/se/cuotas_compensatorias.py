"""Cuotas compensatorias — resoluciones definitivas de la Secretaría de
Economía (SE), publicadas en el DOF (ADR 0009).

NO ES UN CATÁLOGO ÚNICO, COMO EL ANEXO 2.4.1

Cada cuota compensatoria sale de SU PROPIA resolución del DOF, publicada en
una fecha distinta, con su propio expediente y su propio texto en prosa
libre — no hay una tabla ni un HTML tabular del que extraer todas a la vez.
Por eso este módulo no tiene un parser genérico: cada función de aquí
corresponde a UNA resolución, leída y verificada a mano contra el documento
primario (nunca contra un resumen de prensa ni de un buscador — ver
`docs/adr/0009-cuota-compensatoria-cable-de-acero.md`), con los puntos
exactos citados en el docstring de cada una.

Primera (y por ahora única) cuota cargada: cable de acero originario de
China. Las demás combinaciones candidatas del reconocimiento
(`docs/RECONOCIMIENTO_CUOTAS_COMPENSATORIAS.md`) quedan `NEEDS_VALIDATION`
hasta que ésta funcione de punta a punta (decisión de Persona 1, 6-oct) —
no se verifican 21 antes de tener quien las lea, mismo criterio que evitó
repetir "el patrón del FIX".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ParsedCompensatoryDuty:
    origin_country: str
    fraction_code: str
    exporter_name: str | None
    rate: str
    rate_currency: str
    rate_unit: str
    valid_from: date
    valid_to: date | None
    scope_note: str | None


#: `dof.gob.mx/nota_detalle.php?codigo=5784426&fecha=09/04/2026` — verificado
#: con `curl` + lectura directa del HTML (NO un resumen de WebFetch ni de
#: prensa: la primera vez se citó por error la resolución de 2021 porque la
#: prensa hablaba de "la prórroga de 2026" sin dar el código correcto).
CABLE_ACERO_CHINA_SOURCE_URL = "https://dof.gob.mx/nota_detalle.php?codigo=5784426&fecha=09/04/2026"

CABLE_ACERO_CHINA_SOURCE_DOCUMENT = (
    "RESOLUCIÓN final del procedimiento administrativo de examen de vigencia "
    "de la cuota compensatoria impuesta a las importaciones de cables de "
    "acero originarias de la República Popular China, independientemente "
    "del país de procedencia (expediente EC 32-24, DOF 2026-04-09)"
)

#: Punto 214 de la resolución, verbatim: "Se prórroga la vigencia de la
#: cuota compensatoria... de 2.58 dólares por kilogramo... por cinco años
#: más, contados a partir del 17 de diciembre de 2024." -- la propia
#: resolución fija el término: NO es una vigencia abierta que se cierre con
#: la fila siguiente (al contrario que `ExchangeRate`), es la fecha que la
#: norma misma declara.
_VALID_FROM = date(2024, 12, 17)
_VALID_TO = date(2029, 12, 17)

#: Punto 213, verbatim: "...que ingresan a través de las fracciones
#: arancelarias de la TIGIE 7312.10.01, 7312.10.05, 7312.10.07 y
#: 7312.10.99, o por cualquier otra." -- la cuota sigue a la MERCANCÍA/
#: ORIGEN, no sólo a estas cuatro fracciones. `scope_note` lo deja escrito
#: en cada fila para que un consumidor futuro no asuma que la ausencia de
#: una fracción en esta tabla significa que no aplica.
_NOTA_ALCANCE = (
    "La resolución (punto 213) dice que la mercancía 'ingresa por' estas "
    "fracciones 'o por cualquier otra' -- la cuota sigue al ORIGEN "
    "(China) y a la MERCANCÍA (cables de acero), no sólo a las fracciones "
    "listadas aquí. Sin exportador nombrado con tasa distinta: una sola "
    "tasa para todo origen China (verificado en el texto completo, no sólo "
    "en el título)."
)

_FRACCIONES = ("73121001", "73121005", "73121007", "73121099")


def cable_de_acero_china() -> list[ParsedCompensatoryDuty]:
    """Las 4 fracciones de la resolución EC 32-24, una fila cada una.

    `rate` va como `str`, no `Decimal`: el parser no decide la precisión
    final, eso es contrato de la columna NUMERIC(18,6) en la base (§8.1,
    "el LLM/el parser no calculan, citan").
    """
    return [
        ParsedCompensatoryDuty(
            origin_country="CN",
            fraction_code=fraccion,
            exporter_name=None,
            rate="2.58",
            rate_currency="USD",
            rate_unit="KG",
            valid_from=_VALID_FROM,
            valid_to=_VALID_TO,
            scope_note=_NOTA_ALCANCE,
        )
        for fraccion in _FRACCIONES
    ]
