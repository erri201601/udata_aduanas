"""SAT Datos Abiertos: cifras de comercio exterior por mes (ADR 0021).

LA FUENTE

`sat.gob.mx/minisitio/DatosAbiertos/dyp.html` enlaza tres `.xls` (BIFF) de
comercio exterior, mensuales desde 2010:

- `FORMATO_43_ImpNum.xls`: millones de pedimentos pagados de importación.
- `FORMATO_44_ExpNum.xls`: lo mismo, de exportación.
- `FORMATO_59_RecDerImp.xls`: millones de pesos recaudados por comercio
  exterior, por impuesto (IVA, IGI, DTA, IEPS, ISAN, otros y total).

ACUMULADAS O DEL MES: SE COMPRUEBA, NO SE SUPONE

El archivo no dice si una cifra es del mes o acumulada en el año. Los
pedimentos crecen mes a mes y vuelven a empezar cada enero (agosto de 2026:
5.3 millones, lo que no puede ser un solo mes). La recaudación sube y baja. Se
comprueba en cada año: si una serie dice ser acumulada y algún mes baja, la
carga se detiene (`NEEDS_VALIDATION`) en vez de guardar una cifra mal leída.

Las notas al pie se guardan verbatim en cada fila.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Final

import xlrd

FUENTE: Final = "SAT"
OCHO_DECIMALES: Final = Decimal("0.00000001")
BASE: Final = "https://wu1agsprosta001.blob.core.windows.net/agsc-publicaciones/Datos_abiertos/Cifras_SAT/Documents"
PAGINA: Final = "https://www.sat.gob.mx/minisitio/DatosAbiertos/dyp.html"

MESES: Final = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


@dataclass(frozen=True)
class Archivo:
    nombre: str
    #: Nombre de serie por columna de valor (a partir de la tercera).
    series: tuple[str, ...]
    unidad: str
    acumulada: bool


ARCHIVOS: Final = (
    Archivo("FORMATO_43_ImpNum.xls", ("PEDIMENTOS_IMPORTACION",), "millones de pedimentos", True),
    Archivo("FORMATO_44_ExpNum.xls", ("PEDIMENTOS_EXPORTACION",), "millones de pedimentos", True),
    Archivo(
        "FORMATO_59_RecDerImp.xls",
        (
            "RECAUDACION_IVA",
            "RECAUDACION_IGI",
            "RECAUDACION_DTA",
            "RECAUDACION_IEPS",
            "RECAUDACION_ISAN",
            "RECAUDACION_OTROS",
            "RECAUDACION_TOTAL",
        ),
        "millones de pesos",
        False,
    ),
)


class CifrasIlegiblesError(ValueError):
    """El archivo no tiene la forma conocida, o una serie acumulada baja."""


@dataclass(frozen=True)
class Cifra:
    serie: str
    anio: int
    mes: int
    valor: Decimal
    unidad: str
    acumulada: bool
    notas: str | None


def _decimal(valor: object) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        # xlrd entrega float: se pasa por `repr`, que es la representación
        # más corta que vuelve al mismo float, y de ahí a Decimal.
        crudo = Decimal(repr(valor)) if isinstance(valor, float) else Decimal(str(valor).strip())
        # Ocho decimales, como la columna: millones de pesos hasta el centavo.
        # Más allá sólo hay ruido binario del float («…440000004»).
        return crudo.quantize(OCHO_DECIMALES)
    except InvalidOperation:
        return None


def filas_de_xls(datos: bytes) -> list[list[object]]:
    """La primera hoja del `.xls`, fila por fila, tal cual la da xlrd."""
    hoja = xlrd.open_workbook(file_contents=datos).sheet_by_index(0)
    return [[hoja.cell_value(r, c) for c in range(hoja.ncols)] for r in range(hoja.nrows)]


def leer(datos: bytes, archivo: Archivo) -> list[Cifra]:
    """Las cifras de un `.xls` del SAT."""
    return leer_filas(filas_de_xls(datos), archivo)


def leer_filas(hoja: list[list[object]], archivo: Archivo) -> list[Cifra]:
    """Las cifras de las filas de la hoja (separado para probarlo sin `.xls`)."""
    notas: list[str] = []
    filas: list[tuple[int, int, list[Decimal | None]]] = []
    anio_actual: int | None = None
    for r, celdas in enumerate(hoja):
        texto = [str(c).strip() for c in celdas]
        mes = MESES.get(texto[2].lower().rstrip("*").strip()) if len(texto) > 2 else None
        if mes is not None:
            anio_celda = _decimal(celdas[1])
            if anio_celda is not None:
                anio_actual = int(anio_celda)
            if anio_actual is None:
                raise CifrasIlegiblesError(f"{archivo.nombre}: mes sin año en la fila {r + 1}")
            valores = [_decimal(c) for c in celdas[3 : 3 + len(archivo.series)]]
            filas.append((anio_actual, mes, valores))
            continue
        largo = next((t for t in texto if len(t) > 30), None)
        if largo and (largo.startswith(("*", "Las cifras", "Fuente"))):
            notas.append(largo)
    if not filas:
        raise CifrasIlegiblesError(f"{archivo.nombre}: ninguna fila de año y mes")
    nota = "\n".join(dict.fromkeys(notas)) or None

    salida: list[Cifra] = []
    for i, serie in enumerate(archivo.series):
        previo: tuple[int, Decimal] | None = None
        for anio, mes, valores in filas:
            valor = valores[i] if i < len(valores) else None
            if valor is None:
                continue
            if archivo.acumulada and previo and previo[0] == anio and valor < previo[1]:
                raise CifrasIlegiblesError(
                    f"{archivo.nombre}: {serie} baja en {anio}-{mes:02d} y debería ser "
                    "acumulada en el año (NEEDS_VALIDATION)"
                )
            previo = (anio, valor)
            salida.append(Cifra(serie, anio, mes, valor, archivo.unidad, archivo.acumulada, nota))
    return salida


def es_acumulada_por_los_datos(cifras: list[Cifra]) -> bool:
    """¿Crece en cada año y vuelve a empezar en enero? Lo usa la prueba de que
    la recaudación NO es acumulada."""
    por_anio: dict[int, list[Decimal]] = {}
    for c in sorted(cifras, key=lambda c: (c.anio, c.mes)):
        por_anio.setdefault(c.anio, []).append(c.valor)
    return all(all(b >= a for a, b in pairwise(v)) for v in por_anio.values() if len(v) > 1)
