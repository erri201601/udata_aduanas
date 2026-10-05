"""RAW -> PARSED del Anexo 2.4.1 — la correlación fracción → NOM (ADR 0003).

QUÉ ES Y POR QUÉ NO ES EL 2.2.1

El Anexo 2.2.1 del Acuerdo de la SE es de PERMISOS PREVIOS. La correlación
fracción → NOM vive en el **2.4.1** («Anexo de NOM's»), del Capítulo 2.4 del
mismo Acuerdo. Lo verificó Persona 2 el 28-sep y el ADR 0003 lo documenta.

LA ACOTACIÓN NO ES UN ADORNO

Buena parte de las filas traen un «Únicamente: …» que limita la NOM a un
subconjunto de la fracción — a veces por producto (sólo leche descremada,
dentro de una fracción de leche en polvo), a veces por punto de la norma (sólo
el punto 9.2).

Un mapeo que ignore la acotación afirma una NOM que no siempre aplica, y
`MISSING_NOM` es una acusación contra el agente aduanal. Por eso se guarda el
texto íntegro y el lado de lectura decide: sólo las filas SIN acotación
alimentan `required_nom_codes`; las acotadas se reportan aparte, para que las
lea una persona.

TRES COLUMNAS DE ANCHO FIJO

`pdftotext -layout` conserva las columnas por posición de carácter:

        1-12         17-65                      66+
    0402.10.01   Leche en polvo…        NOM-222-SCFI/SAGARPA-
                                        2018
            00   Leche en polvo…        Únicamente: Leche en polvo o
                                        deshidratada descremada.

La fracción manda. El NICO va indentado bajo ella, y tanto el código de la NOM
como la acotación se parten en varias líneas — así que se acumulan hasta que
empieza otra fila.

SE AGRUPA POR FRACCIÓN, NO POR NICO — Y HAY UNA RAZÓN

El anexo distingue NICO dentro de una fracción, y sería más fino guardarlos. No
se hace, porque el PDF linealizado no permite atribuirlos con seguridad: la
celda de la NOM abarca varias filas visualmente y, al linealizar, su texto
aparece UNA LÍNEA ANTES del NICO al que pertenece.

    1806.90.99     Los demás.
                   Preparaciones alimenticias…
                   partidas 04.01 a 04.04…          NOM-186-SSA1/SCFI-2013   ← aquí
             01    cacao en una proporción…         Únicamente: …            ← pertenece a esto

Atribuirlo por posición acertaría casi siempre y fallaría en silencio el resto,
y un `MISSING_NOM` mal atribuido acusa a un agente aduanal. Se agrupa por
fracción —más grueso y siempre cierto— y la precisión por NICO queda como deuda
documentada, para cuando haya una fuente tabular en vez de un PDF.

NUMERALES 1, 2 Y 4

Son los tabulares. El 3 (etiquetado) tiene otra estructura —listas en romanos
por capítulo de norma— y queda fuera, como fijó el ADR. El 5 (NOM de
emergencia) está vacío en la versión vigente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

#: Dónde empieza cada columna en el texto linealizado.
_COL_DESCRIPCION: Final[int] = 16
#: Un carácter antes de donde empieza el texto de la derecha. Estaba en 65 y
#: una NOM que arrancara justo ahí perdía su «N»: el patrón exige «NOM-» y
#: recibía «OM-». Se corta algo antes y los patrones —específicos— se encargan.
_COL_NOM: Final[int] = 62

#: Una fracción de la Tarifa, tal como la escribe el anexo: con puntos.
_FRACCION = re.compile(r"^\s{0,6}(\d{4})\.(\d{2})\.(\d{2})\b")
#: Un NICO: dos dígitos solos, indentados bajo su fracción.
_NICO = re.compile(r"^\s{7,}(\d{2})\s")
#: El código de una NOM. Admite las compuestas: NOM-222-SCFI/SAGARPA-2018.
_NOM = re.compile(r"NOM-[\w./-]*\d{4}")
#: Lo que limita la NOM a una parte de la fracción.
_ACOTACION = re.compile(r"[ÚU]nicamente\s*:\s*(.+)", re.IGNORECASE)
#: Dónde empieza cada numeral del anexo.
_NUMERAL = re.compile(r"^(\d)\.-\s")

#: Los numerales con forma de tabla. El 3 y el 5 quedan fuera (ver docstring).
NUMERALES_TABULARES: Final[tuple[int, ...]] = (1, 2, 4)


@dataclass
class FilaNom:
    """Una fracción (o su NICO) sujeta a una NOM."""

    fraction_code: str
    """Ocho dígitos, SIN puntos — como los guarda `tariff_fractions`."""
    nico: str | None  # Siempre `None` hoy: ver «SE AGRUPA POR FRACCIÓN» arriba.
    numeral: int
    nom_code: str
    scope_note: str | None = None
    """El «Únicamente: …» íntegro, o `None` si la NOM aplica a toda la fila."""


@dataclass
class _EnCurso:
    """La fila que se está leyendo, mientras llegan sus continuaciones."""

    fraction_code: str = ""
    nico: str | None = None
    numeral: int = 0
    derecha: list[str] = field(default_factory=list)
    """La columna de la NOM, línea a línea. Se junta al cerrar.

    No se extrae sobre la marcha porque el código de la norma SE PARTE entre
    líneas —«NOM-222-SCFI/SAGARPA-» y «2018» abajo— y un patrón aplicado línea
    a línea no ve ninguno de los dos trozos. La primera versión perdía así una
    de cada cuatro filas.
    """

    def cerrar(self) -> list[FilaNom]:
        """Las filas que deja esta entrada. Una por NOM citada.

        Sin NOM no se devuelve nada: una fila del anexo sin norma que citar no
        es una obligación, y guardarla como si lo fuera inventaría una.
        """
        if not self.fraction_code:
            return []
        # Se junta la columna y se le quitan los cortes de línea: así
        # «NOM-222-SCFI/SAGARPA-\n2018» vuelve a ser un código.
        junto = re.sub(r"-\s+(?=\d)", "-", " ".join(self.derecha))
        junto = " ".join(junto.split())
        noms = list(dict.fromkeys(_NOM.findall(junto)))
        if not noms:
            return []

        acotada = _ACOTACION.search(junto)
        nota = acotada.group(1).strip() if acotada else None
        return [
            FilaNom(
                fraction_code=self.fraction_code,
                nico=self.nico,
                numeral=self.numeral,
                nom_code=nom,
                scope_note=nota,
            )
            for nom in noms
        ]


def _columna_nom(linea: str) -> str:
    return linea[_COL_NOM:] if len(linea) > _COL_NOM else ""


def parse(texto: str) -> list[FilaNom]:
    """Las filas del anexo, de los numerales tabulares.

    No se detiene ante una línea rara: el anexo trae encabezados repetidos,
    pies de página y saltos de sección entre medias. Lo que no encaja se ignora
    en silencio, y lo que sí se acumula hasta que empieza otra fila.
    """
    salida: list[FilaNom] = []
    actual = _EnCurso()
    numeral = 0

    for linea in texto.splitlines():
        marca = _NUMERAL.match(linea)
        if marca:
            salida.extend(actual.cerrar())
            actual = _EnCurso()
            numeral = int(marca.group(1))
            continue

        if numeral not in NUMERALES_TABULARES:
            continue

        fraccion = _FRACCION.match(linea)
        if fraccion:
            salida.extend(actual.cerrar())
            actual = _EnCurso(
                fraction_code="".join(fraccion.groups()),
                numeral=numeral,
            )
            _acumular(actual, linea)
            continue

        if actual.fraction_code:
            _acumular(actual, linea)

    salida.extend(actual.cerrar())
    return salida


def _acumular(actual: _EnCurso, linea: str) -> None:
    """Guarda la columna de la derecha. Lo que diga se interpreta al cerrar."""
    derecha = _columna_nom(linea).strip()
    if derecha:
        actual.derecha.append(derecha)
