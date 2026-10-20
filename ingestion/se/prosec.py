"""Decreto PROSEC, artículo 5: la tasa de cada sector para cada insumo (ADR 0011).

FUENTE

Compilación de la Secretaría de Economía en SNICE, con reformas hasta el DOF del
26-08-2024 (`SOURCE_URL`). La landing del §11 (`programasdefom.prosec.html`) no
tiene tablas: el reconocimiento de Persona 2 (`docs/RECONOCIMIENTO_PROSEC_Y_REGLA_8A.md`,
13-oct) localizó este documento.

QUÉ SE LEE

Sólo el artículo 5: por sector (incisos I a XXIV), los bienes que el productor
autorizado puede importar con el arancel que se indica. Cuatro columnas:
código, descripción, arancel (%) y acotación.

- En el ARANCEL, «Ex.» es **exento**: tasa 0.
- En la ACOTACIÓN, «Únicamente: …» o «Excepto: …» acota la fracción: el
  beneficio cubre sólo parte de ella (`is_partial`).

POR QUÉ CELDAS Y NO TEXTO

`pdftotext -layout` reparte la columna de acotación entre filas vecinas: el
texto de una fila acababa asignado a la de al lado. Las tablas del PDF tienen
celdas reales, y `pdfplumber` las devuelve. Pero en el sector XIX las filas se
parten en varias columnas espaciadoras y el código cae a veces en la primera y
a veces en la segunda: por eso cada celda se asigna a la columna del ENCABEZADO
que contiene su centro horizontal, y no por su índice.

Comprobado el 20-oct contra el texto del mismo PDF: 2 649 filas en las dos
extracciones, 0 diferencias de tasa, y las 895 fracciones distintas existen
vigentes en la LIGIE cargada.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

SOURCE_URL: Final = (
    "https://www.snice.gob.mx/~oracle/SNICE_DOCS/DECRETO-PROSEC-BIBLIOTECA_20240826-20240826.pdf"
)
SOURCE_DOCUMENT: Final = (
    "Decreto por el que se establecen diversos Programas de Promoción Sectorial "
    "(DOF 02-08-2002), compilación SNICE con reformas hasta el DOF 26-08-2024"
)
#: Última reforma que incluye la compilación. Antes de esta fecha no se afirma
#: ninguna tasa: puede que no rigiera todavía (NEEDS_VALIDATION, ADR 0011).
VALID_FROM: Final = date(2024, 8, 26)
PUBLISHED_AT: Final = date(2024, 8, 26)

_SECTOR = re.compile(r"^\s*([IVXL]+)\.\s+(De (?:la|las) .+?):?\s*$")
_CODIGO = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
_TASA = re.compile(r"^(Ex\.?|\d{1,2}(?:\.\d{1,2})?)$")
_CAMPOS: Final = ("CÓDIGO", "DESCRIPCIÓN", "ARANCEL", "ACOTACIÓN")


@dataclass(frozen=True)
class FilaProsec:
    sector_code: str
    """El inciso del artículo 5: «I», «XIX»."""
    sector_name: str
    """«Industria Eléctrica»: el nombre del inciso sin «De la»."""
    fraction_code: str
    """Ocho dígitos, sin puntos."""
    igi_rate: Decimal
    """Como fracción: «Ex.» = 0, «5» = 0.05."""
    acotacion: str | None
    """«Únicamente: …» o «Excepto: …», íntegra. `None` = toda la fracción."""
    descripcion: str

    @property
    def is_partial(self) -> bool:
        return self.acotacion is not None


def tasa(texto: str) -> Decimal:
    """«Ex.» → 0; «5» → 0.05; «2.5» → 0.025. Lanza si no es una tasa."""
    t = texto.strip()
    if not _TASA.match(t):
        raise ValueError(f"no es una tasa del decreto: {texto!r}")
    if t.startswith("Ex"):
        return Decimal("0")
    return (Decimal(t) / Decimal(100)).quantize(Decimal("0.000001"))


def nombre_de_sector(encabezado: str) -> str:
    """«De la Industria Eléctrica» → «Industria Eléctrica»."""
    return re.sub(r"^De (?:la|las)\s+", "", encabezado.strip().rstrip(":")).strip()


def _limpio(texto: str) -> str:
    return " ".join(texto.split())


@dataclass
class _Cruda:
    sector: tuple[str, str]
    codigo: str
    descripcion: list[str]
    tasa: str
    acotacion: list[str]


def filas_de_celdas(
    eventos: Iterable[tuple[str, Any]],
) -> list[FilaProsec]:
    """Arma las filas a partir de eventos ya ordenados de arriba abajo.

    Cada evento es `("ini" | "fin", None)`, `("sector", (código, encabezado))`
    o `("fila", [(x0, x1, texto), …])`: las celdas no vacías de una fila de
    tabla, con su posición horizontal. Separado de `pdfplumber` para poder
    probarlo sin un PDF.

    - Una fila con «CÓDIGO» es un encabezado: fija la geometría de columnas.
    - Una fila sin código continúa la anterior (salto de página o línea
      partida en el sector XIX).
    """
    dentro = False
    sector: tuple[str, str] | None = None
    geometria: dict[str, tuple[float, float]] | None = None
    crudas: list[_Cruda] = []

    for tipo, carga in eventos:
        if tipo == "ini":
            dentro = True
            continue
        if tipo == "fin":
            if dentro:
                break
            continue
        if not dentro:
            continue
        if tipo == "sector":
            sector = carga
            continue
        if tipo != "fila" or sector is None:
            continue
        celdas: Sequence[tuple[float, float, str]] = carga
        if any(t.startswith("CÓDIGO") for _, _, t in celdas):
            geo = {
                campo: (x0, x1) for x0, x1, t in celdas for campo in _CAMPOS if t.startswith(campo)
            }
            if len(geo) >= 3:
                geometria = geo
            continue
        if geometria is None:
            continue
        por_campo: dict[str, list[str]] = defaultdict(list)
        for x0, x1, t in celdas:
            # `_continua` y no `append`: en el XIX la cola de una celda partida
            # llega además como otra celda en la misma columna.
            _continua(por_campo[_columna((x0 + x1) / 2, geometria)], [t])
        codigo = _limpio(" ".join(por_campo["CÓDIGO"]))
        if _CODIGO.match(codigo):
            crudas.append(
                _Cruda(
                    sector=sector,
                    codigo=codigo,
                    descripcion=list(por_campo["DESCRIPCIÓN"]),
                    tasa=_limpio(" ".join(por_campo["ARANCEL"])),
                    acotacion=list(por_campo["ACOTACIÓN"]),
                )
            )
        elif not codigo and crudas and crudas[-1].sector == sector:
            anterior = crudas[-1]
            _continua(anterior.descripcion, por_campo["DESCRIPCIÓN"])
            _continua(anterior.acotacion, por_campo["ACOTACIÓN"])
            if not anterior.tasa:
                anterior.tasa = _limpio(" ".join(por_campo["ARANCEL"]))

    return [
        FilaProsec(
            sector_code=c.sector[0],
            sector_name=nombre_de_sector(c.sector[1]),
            fraction_code=c.codigo.replace(".", ""),
            igi_rate=tasa(c.tasa),
            acotacion=_sin_cola_repetida(_limpio(" ".join(c.acotacion))) or None,
            descripcion=_limpio(" ".join(c.descripcion)),
        )
        for c in crudas
    ]


_COLA_REPETIDA = re.compile(r"(\S.{5,}?) \1$")


def _sin_cola_repetida(texto: str) -> str:
    """«…dispersiones y soluciones. dispersiones y soluciones.» → una vez.

    En el sector XIX la última línea de una celda partida entre páginas llega
    dos veces por caminos que el PDF no distingue. Un texto legal que repita
    literalmente su propia cola no existe; quitarla es seguro.
    """
    while m := _COLA_REPETIDA.search(texto):
        texto = texto[: m.start()] + m.group(1)
    return texto


def _continua(acumulado: list[str], fragmentos: list[str]) -> None:
    """Añade la continuación de una celda, sin repetir lo que ya trae.

    En el sector XIX la celda partida llega completa en la primera fila y su
    última línea vuelve a aparecer como fila de continuación: sin esto, la
    acotación acababa en «…dispersiones y soluciones. dispersiones y
    soluciones.».
    """
    for fragmento in fragmentos:
        if _limpio(" ".join(acumulado)).endswith(_limpio(fragmento)):
            continue
        acumulado.append(fragmento)


def _columna(x: float, geometria: dict[str, tuple[float, float]]) -> str:
    """La columna del encabezado que contiene `x`; si ninguna, la más cercana."""

    def distancia(intervalo: tuple[float, float]) -> float:
        x0, x1 = intervalo
        return 0.0 if x0 <= x <= x1 else min(abs(x - x0), abs(x - x1))

    return min(geometria, key=lambda campo: distancia(geometria[campo]))


def parse_prosec(pdf_path: str) -> list[FilaProsec]:
    """Las filas del artículo 5 del PDF del decreto."""
    import pdfplumber

    eventos: list[tuple[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pagina in pdf.pages:
            de_pagina: list[tuple[float, str, Any]] = []
            lineas = pagina.extract_text_lines()
            for k, linea in enumerate(lineas):
                texto = linea["text"]
                if "ARTÍCULO 5.-" in texto:
                    de_pagina.append((linea["top"], "ini", None))
                if "ARTÍCULO 6.-" in texto:
                    de_pagina.append((linea["top"], "fin", None))
                m = _SECTOR.match(texto)
                if m:
                    nombre = m.group(2)
                    # El encabezado puede ocupar dos líneas (XIV, XV): sin los
                    # dos puntos, el nombre sigue en la siguiente.
                    if not texto.rstrip().endswith(":") and k + 1 < len(lineas):
                        nombre = f"{nombre} {lineas[k + 1]['text'].strip()}"
                    de_pagina.append((linea["top"], "sector", (m.group(1), nombre)))
            for tabla in pagina.find_tables():
                for fila, textos in zip(tabla.rows, tabla.extract(), strict=False):
                    celdas = [
                        (c[0], c[2], (t or "").strip())
                        for c, t in zip(fila.cells, textos, strict=False)
                        if c is not None and (t or "").strip()
                    ]
                    if celdas:
                        de_pagina.append((fila.bbox[1], "fila", celdas))
            eventos += [(tipo, carga) for _, tipo, carga in sorted(de_pagina, key=lambda e: e[0])]
    return filas_de_celdas(eventos)
