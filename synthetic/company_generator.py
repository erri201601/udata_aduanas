"""`CompanyGenerator` (§24 maestro): importadores sintéticos nuevos.

Los 15 importadores del corpus ya cargado siguen el patrón `SIM260101A<letra>`
(uno por pedimento, nunca comparten `Client`, ver `ingestion/sintetico/
load.py::_get_or_create_client`). Este generador continúa esa MISMA
secuencia -- no inventa un esquema de RFC nuevo, sólo las siguientes letras
que el corpus original no usó (`AP`, `AQ`, ...).
"""

from __future__ import annotations

import string
from dataclasses import dataclass


@dataclass(frozen=True)
class CompanyFicha:
    rfc: str
    name: str
    address: str


_PREFIJO_RFC = "SIM260101"
#: Las 15 letras que ya usó el corpus original (`AA`..`AO`) -- empezar
#: después de éstas es lo que garantiza no colisionar con un `Client` ya
#: cargado (`UniqueConstraint` no existe sobre `rfc`, pero reusar un RFC ya
#: cargado reutilizaría ESE `Client`, con SU propio id -- confuso para
#: trazar qué importador es cuál en un corpus nuevo).
_LETRAS_YA_USADAS = 15


def _sufijo(indice: int) -> str:
    """0 -> "AP", 1 -> "AQ", ... -- misma convención de 2 letras A-Z."""
    letras = string.ascii_uppercase
    total = _LETRAS_YA_USADAS + indice
    primera, segunda = divmod(total, len(letras))
    return f"{letras[primera]}{letras[segunda]}"


def generar_importador(indice: int, *, numero_laboratorio: int) -> CompanyFicha:
    """Un importador nuevo, secuencial, mismo estilo que el corpus original
    (`IMPORTADORA LABORATORIO NN SA DE CV`, misma dirección de prueba)."""
    rfc = f"{_PREFIJO_RFC}{_sufijo(indice)}"
    return CompanyFicha(
        rfc=rfc,
        name=f"IMPORTADORA LABORATORIO {numero_laboratorio:02d} SA DE CV",
        address="AV. DATOS DE PRUEBA 101, COL. LABORATORIO, C.P. 01000, CIUDAD DE MEXICO",
    )
