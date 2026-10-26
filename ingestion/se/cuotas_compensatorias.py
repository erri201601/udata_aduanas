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
    #: Fecha real de publicación en el DOF de la resolución (distinta de
    #: `valid_from`, que es cuándo empieza a correr la vigencia que la
    #: propia resolución declara — aquí, el inicio del término de 5 años).
    published_at: date
    #: Palabras que la partida tiene que decir (ver `CompensatoryDuty.product_terms`).
    product_terms: tuple[str, ...] = ()


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

#: DOF 2026-04-09 (ver `CABLE_ACERO_CHINA_SOURCE_URL`/`_SOURCE_DOCUMENT`
#: arriba) — la fecha en que la resolución se publicó, no el inicio de su
#: vigencia. No son la misma fecha: confundirlas fue el bug.
_PUBLISHED_AT = date(2026, 4, 9)

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
            published_at=_PUBLISHED_AT,
        )
        for fraccion in _FRACCIONES
    ]


# ── Ollas de presión de aluminio, China (DOF 2026-03-06) ─────────────────────

#: Verificado con `curl` + lectura del HTML del DOF (26-oct), puntos 194-195.
OLLAS_PRESION_CHINA_SOURCE_URL = (
    "https://dof.gob.mx/nota_detalle.php?codigo=5781643&fecha=06/03/2026"
)
OLLAS_PRESION_CHINA_SOURCE_DOCUMENT = (
    "Resolución final del procedimiento administrativo de examen de vigencia de la cuota "
    "compensatoria impuesta a las importaciones de ollas de presión de aluminio originarias "
    "de la República Popular China (DOF 2026-03-06)"
)


def ollas_de_presion_china() -> list[ParsedCompensatoryDuty]:
    """92.64 % sobre el valor, cinco años desde el 27-dic-2024.

    Punto 195, verbatim: «Se prorroga la vigencia de la cuota compensatoria
    impuesta a las importaciones de ollas de presión de aluminio originarias
    de China, de 92.64% [...] por cinco años más, contados a partir del 27 de
    diciembre de 2024.» Punto 194: «que ingresan a través de la fracción
    arancelaria 7615.10.02 de la TIGIE, o por cualquier otra».

    `XXX` como moneda (ISO 4217, «sin moneda»): una cuota ad valorem no está
    en ninguna; el importe sale en la moneda del valor en aduana.

    Acotada a la MERCANCÍA (`product_terms`): la 7615.10.02 son todos los
    artículos de cocina de aluminio, y ésta es sólo de ollas de presión.
    """
    return [
        ParsedCompensatoryDuty(
            origin_country="CN",
            fraction_code="76151002",
            exporter_name=None,
            rate="92.64",
            rate_currency="XXX",
            rate_unit="PCT",
            valid_from=date(2024, 12, 27),
            valid_to=date(2029, 12, 26),
            scope_note=(
                "Una sola tasa para todas las empresas de China (punto 195). Sólo ollas de "
                "presión de aluminio: la fracción 7615.10.02 abarca más mercancía, y los "
                "artículos para cocinar de aluminio tienen su propia cuota, con precio de "
                "referencia (DOF 2023-03-31 y 2023-07-25), que NO está cargada."
            ),
            published_at=date(2026, 3, 6),
            product_terms=("olla", "presion"),
        )
    ]


# ── Tubería de acero al carbono con costura, India (DOF 2022-10-03 y 2026-04-06) ──

#: Prórroga del 3-oct-2022 (puntos 334-335): cinco años desde el 21-abr-2021.
TUBERIA_INDIA_SOURCE_URL = "https://dof.gob.mx/nota_detalle.php?codigo=5666803&fecha=03/10/2022"
TUBERIA_INDIA_SOURCE_DOCUMENT = (
    "RESOLUCIÓN Final del procedimiento administrativo de examen de vigencia de las cuotas "
    "compensatorias impuestas a las importaciones de tubería de acero al carbono con costura "
    "longitudinal recta y helicoidal, originarias de los Estados Unidos de América, el Reino "
    "de España y la República de la India (DOF 2022-10-03); sigue vigente durante el examen "
    "iniciado el 2026-04-06 (DOF codigo=5784087, punto 29)"
)

#: Las de la resolución (7305.11.02, 7305.12.02, 7305.19.99) con su número en
#: la TIGIE vigente: la 7305.12.02 es hoy la 7305.12.91. La cuota sigue a la
#: mercancía, «o por cualquier otra» (punto 334).
_FRACCIONES_TUBERIA = ("73051102", "73051291", "73051999")


def tuberia_india() -> list[ParsedCompensatoryDuty]:
    """128.24 USD por tonelada métrica, para Welspun y las demás exportadoras.

    El monto es el de la resolución del recurso de revocación del 12-ago-2016
    (antecedente 2 de la del 3-oct-2022): de 81.61 a 128.24 USD/t, «para las
    importaciones originarias de India, provenientes de Welspun Corporation,
    Ltd. y de las demás empresas exportadoras». Una sola tasa: exportador `NULL`.

    VIGENCIA. Cinco años desde el 21-abr-2021 —hasta el 20-abr-2026— y el
    6-abr-2026, antes de vencer, se inició otro examen de vigencia. Su punto
    29: las cuotas «continuarán vigentes mientras se tramita el presente
    procedimiento de examen de vigencia». Por eso `valid_to` va vacío: se
    cierra con la resolución final de ese examen, no antes.
    """
    return [
        ParsedCompensatoryDuty(
            origin_country="IN",
            fraction_code=fraccion,
            exporter_name=None,
            rate="128.24",
            rate_currency="USD",
            rate_unit="TNE",
            valid_from=date(2021, 4, 21),
            valid_to=None,
            scope_note=(
                "Misma tasa para Welspun y para las demás exportadoras: exportador NULL. "
                "Vigente mientras se tramita el examen iniciado el 2026-04-06 (punto 29); "
                "cerrar con su resolución final."
            ),
            published_at=date(2022, 10, 3),
            product_terms=("tuberia",),
        )
        for fraccion in _FRACCIONES_TUBERIA
    ]
