"""Las tablas de una nota del DOF en HTML, con sus celdas combinadas resueltas.

Lo usan los anexos del Acuerdo de Reglas de la SE (2.4.1 y 2.5.1), que el DOF
publica como tablas de Word convertidas a HTML: celdas con `rowspan`, tablas
partidas por cada salto de página y el texto que las separa («1.- Se
identifican…») fuera de las celdas. Librería estándar, sin `bs4` ni `lxml`
(mismo criterio que `ingestion/dof/rgce.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class Celda:
    partes: list[str] = field(default_factory=list)
    filas: int = 1
    columnas: int = 1

    @property
    def texto(self) -> str:
        crudo = re.sub(r"[ \t\xa0]+", " ", "".join(self.partes))
        return "\n".join(linea.strip() for linea in crudo.split("\n") if linea.strip())


@dataclass
class Tabla:
    filas: list[list[Celda]]
    #: El texto que aparece fuera de las celdas entre la tabla anterior y ésta.
    #: Ahí van los encabezados de sección del anexo.
    antes: str


def _entero(valor: str | None) -> int:
    try:
        return max(1, int(valor or 1))
    except ValueError:
        return 1


class _Lector(HTMLParser):
    """Cada nivel de tabla lleva su celda abierta: las tablas de datos del DOF
    van anidadas dentro de una tabla de maquetación.

    El «antes» de una tabla es todo el texto desde que se cerró la anterior
    (de cualquier nivel): ahí cae el encabezado de sección, aunque viva dentro
    de una celda de la maquetación.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tablas: list[Tabla] = []
        self._pila: list[tuple[list[list[Celda]], str]] = []
        self._celdas: list[Celda | None] = []
        self._todo: list[str] = []
        self._ultimo_cierre = 0

    @property
    def _celda(self) -> Celda | None:
        return self._celdas[-1] if self._celdas else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table":
            self._pila.append(([], "".join(self._todo[self._ultimo_cierre :])))
            self._celdas.append(None)
        elif tag == "tr" and self._pila:
            self._pila[-1][0].append([])
        elif tag in ("td", "th") and self._pila and self._pila[-1][0]:
            self._celdas[-1] = Celda(
                filas=_entero(a.get("rowspan")), columnas=_entero(a.get("colspan"))
            )
        elif tag in ("br", "div", "p"):
            if self._celda is not None:
                self._celda.partes.append("\n")
            self._todo.append(" ")

    def handle_endtag(self, tag: str) -> None:
        celda = self._celda
        if tag in ("td", "th") and celda is not None and self._pila:
            self._pila[-1][0][-1].append(celda)
            self._celdas[-1] = None
        elif tag == "table" and self._pila:
            filas, antes = self._pila.pop()
            self._celdas.pop()
            self.tablas.append(Tabla(filas=filas, antes=antes))
            self._ultimo_cierre = len(self._todo)

    def handle_data(self, data: str) -> None:
        if self._celda is not None:
            self._celda.partes.append(data)
        self._todo.append(data)


def tablas(html: str) -> list[Tabla]:
    """Todas las tablas, en el orden en que se cierran (las anidadas antes que
    la que las contiene)."""
    lector = _Lector()
    lector.feed(html)
    return lector.tablas


def cuadricula(filas: list[list[Celda]]) -> list[list[str]]:
    """Resuelve `rowspan`/`colspan`: cada fila sale con todas sus columnas."""
    salida: list[list[str]] = []
    pendientes: dict[int, tuple[str, int]] = {}
    for fila in filas:
        linea: list[str] = []
        columna, k = 0, 0
        while k < len(fila) or columna in pendientes:
            if columna in pendientes:
                texto, quedan = pendientes.pop(columna)
                if quedan > 1:
                    pendientes[columna] = (texto, quedan - 1)
                linea.append(texto)
                columna += 1
                continue
            celda = fila[k]
            k += 1
            for _ in range(celda.columnas):
                linea.append(celda.texto)
                if celda.filas > 1:
                    pendientes[columna] = (celda.texto, celda.filas - 1)
                columna += 1
        salida.append(linea)
    return salida
