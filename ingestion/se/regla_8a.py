"""Regla 8ª: qué fracción 9802.00.xx corresponde a cada sector (ADR 0011).

La fuente es la propia LIGIE, ya cargada en `regulatory.tariff_fractions`: cada
9802.00.01 a .25 dice, en su texto, para qué Programa de Promoción Sectorial
es («Mercancías para el Programa de Promoción Sectorial de la Industria
Eléctrica, cuando las empresas cuenten con la autorización a que se refiere la
Regla 8a…»). No hace falta otro documento: se lee el texto oficial ya
almacenado y se cruza con los sectores del Decreto PROSEC.

QUÉ NO ENTRA, Y SE DICE

- Las 9802 cuyo texto no nombra un programa sectorial (la .24, una mercancía
  concreta; de la .26 a la .38, «al amparo de la autorización…» sin sector).
- Una 9802 que no casa con ningún sector, o que casa con dos igual de bien.

Cada una se devuelve en `sin_sector`, con su motivo: NEEDS_VALIDATION.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Palabras que no distinguen un sector de otro.
_VACIAS: Final = frozenset(
    {
        "de",
        "la",
        "las",
        "del",
        "el",
        "los",
        "y",
        "e",
        "industria",
        "industrias",
        "sector",
        "excepto",
        "similares",
        "a",
    }
)
_PROGRAMA = re.compile(r"Programa de Promoci[oó]n Sectorial de (.+?)(?:,? cuando |$)", re.I)


@dataclass(frozen=True)
class FraccionRegla8a:
    sector_code: str
    sector_name: str
    fraction_code: str
    scope_note: str | None
    """La condición que el texto de la 9802 añade, íntegra, cuando la hay
    («cuando se trate de productores indirectos», exclusiones…)."""


def _palabras(texto: str) -> frozenset[str]:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return frozenset(p for p in re.findall(r"[a-z]+", sin_acentos.lower()) if p not in _VACIAS)


def sector_de(descripcion: str, sectores: Mapping[str, str]) -> tuple[str | None, str]:
    """El sector del programa que nombra el texto de una 9802, y por qué.

    Gana el sector cuyas palabras están TODAS en el programa nombrado y que
    tiene más palabras: «Transporte, excepto Automotriz y Autopartes» contiene
    las de «Automotriz y Autopartes», pero es más específico.
    """
    m = _PROGRAMA.search(descripcion)
    if m is None:
        return None, "el texto no nombra un Programa de Promoción Sectorial"
    programa = _palabras(m.group(1))
    candidatos = [
        (len(palabras), codigo)
        for codigo, nombre in sectores.items()
        if (palabras := _palabras(nombre)) and palabras <= programa
    ]
    if not candidatos:
        return None, f"ningún sector del decreto casa con «{m.group(1).strip()}»"
    candidatos.sort(reverse=True)
    if len(candidatos) > 1 and candidatos[0][0] == candidatos[1][0]:
        return None, f"casa igual con los sectores {candidatos[0][1]} y {candidatos[1][1]}"
    return candidatos[0][1], ""


def _condicion(descripcion: str) -> str | None:
    """Lo que el texto añade después del programa: productores directos o
    indirectos, exclusiones. `None` si sólo remite a la autorización."""
    texto = " ".join(descripcion.split())
    # Hasta «, cuando las empresas…» o el final: un punto no corta, porque
    # las fracciones citadas llevan puntos («9802.00.24»).
    especifica = re.search(
        r"(cuando se trate de .+?|excepto l[oa]s? comprendid[oa]s? .+?)"
        r"(?=,? (?:y )?(?:cuando )?las empresas cuenten|,? cuando las empresas|\.?$)",
        texto,
        re.I,
    )
    return especifica.group(1).strip() if especifica else None


def fracciones_regla_8a(
    fracciones: Sequence[tuple[str, str]],
    sectores: Mapping[str, str],
) -> tuple[list[FraccionRegla8a], list[str]]:
    """`(fracción, texto)` de las 9802 vigentes → las de cada sector, y las que no.

    `sectores` es inciso → nombre, tal como salen del Decreto PROSEC.
    """
    resueltas: list[FraccionRegla8a] = []
    sin_sector: list[str] = []
    for codigo, descripcion in fracciones:
        if not codigo.startswith("9802"):
            continue
        sector, motivo = sector_de(descripcion, sectores)
        if sector is None:
            sin_sector.append(f"{codigo}: {motivo} (NEEDS_VALIDATION)")
            continue
        resueltas.append(
            FraccionRegla8a(
                sector_code=sector,
                sector_name=sectores[sector],
                fraction_code=codigo,
                scope_note=_condicion(descripcion),
            )
        )
    return resueltas, sin_sector
