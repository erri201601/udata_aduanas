"""RAW -> PARSED del Anexo 2.5.1: dónde hay cuota compensatoria (ADR 0017).

LA FUENTE

Acuerdo por el que se modifica al diverso por el que la SE emite reglas y
criterios de carácter general en materia de comercio exterior, DOF 25-nov-2022
(`codigo=5672457`). Su punto Único reforma «los Anexos 2.2.1, 2.2.2, 2.4.1 y
2.5.1» y los publica completos. En el índice de SNICE no hay, hasta el
15-oct-2026, otro acuerdo que vuelva a tocar el 2.5.1 (se revisaron los diez
posteriores).

Rige desde el 12-dic-2022. El Transitorio Primero lo hace entrar en vigor «el
mismo día» que la LIGIE del 7-jun-2022, y la Cuarta Resolución de
Modificaciones a las RGCE 2022 (DOF 5-dic-2022, punto SEGUNDO) fija esa fecha.

UN ÍNDICE, NO UNA TARIFA

Regla 2.5.3 del mismo Acuerdo: si el anexo y la resolución discrepan,
«prevalecerán estas últimas». Por eso aquí no se convierte ninguna cuota en
número. El texto de la columna CUOTA COMPENSATORIA se guarda tal cual: es lo
que dice el anexo, y sirve para saber DÓNDE mirar. El importe sigue saliendo
de la resolución, leída y verificada (ADR 0009, `compensatory_duties`).

Y es una foto de noviembre de 2022: la regla 2.5.4 manda actualizarlo cada seis
meses y no se ha hecho. Una cuota que se eliminó o se prorrogó después no se ve
aquí. Por eso cada fila guarda la fecha de su última resolución citada.

LA TABLA

El HTML del DOF parte el anexo en diez tablas por los saltos de página, con
celdas combinadas (`rowspan`). Una tabla que empieza con PRODUCTO, FRACCIÓN y
PAÍS vacíos continúa el registro de la anterior. Dentro de un registro:

- la columna de fechas es el historial de resoluciones, una por fila;
- EMPRESAS y CUOTA van en pares. Una fila con la misma empresa, o sin empresa,
  y otro texto de cuota es una nota del par anterior (por ejemplo, «Elusión…»
  o «la Secretaría determina no aplicar…»), y se le añade.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from typing import Final

SOURCE_URL: Final = "https://dof.gob.mx/nota_detalle.php?codigo=5672457&fecha=25/11/2022"
SOURCE_DOCUMENT: Final = (
    "Anexo 2.5.1 del Acuerdo de Reglas de la SE, reformado por el Acuerdo publicado en el "
    "DOF el 25-nov-2022 (codigo=5672457)"
)
PUBLISHED_AT: Final = date(2022, 11, 25)
#: Cuarta Resolución de Modificaciones a las RGCE 2022, DOF 5-dic-2022, punto
#: SEGUNDO: la LIGIE «entrará en vigor el 12 de diciembre de 2022».
VALID_FROM: Final = date(2022, 12, 12)

ENCABEZADO: Final = (
    "PRODUCTO",
    "FRACCION",
    "PAÍS",
    "FECHA DE PUBLICACIÓN",
    "EMPRESAS",
    "CUOTA COMPENSATORIA",
)

#: Los países tal como los escribe el anexo. Sin heurística: un país nuevo
#: detiene la carga, porque adivinar un origen es inventar a quién se le cobra.
#: «COREA» es la República de Corea: así la nombran las resoluciones de la SE.
PAISES: Final[dict[str, str]] = {
    "ALEMANIA": "DE",
    "ARGENTINA": "AR",
    "BRASIL": "BR",
    "CHINA": "CN",
    "COREA": "KR",
    "ESPAÑA": "ES",
    "EUA": "US",
    "FRANCIA": "FR",
    "INDIA": "IN",
    "ITALIA": "IT",
    "JAPÓN": "JP",
    "KAZAJSTÁN": "KZ",
    "PORTUGAL": "PT",
    "REINO UNIDO": "GB",
    "RUMANIA": "RO",
    "RUSIA": "RU",
    "TAIWÁN": "TW",
    "UCRANIA": "UA",
}

_FRACCION = re.compile(r"\b(\d{4})\.(\d{2})\.(\d{2})\b")
_FECHA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
#: «TODAS LAS EXPORTADORAS», «TODAS LAS DEMÁS EMPRESAS», «STUPP BROS., INC Y
#: TODAS LAS DEMÁS EXPORTADORAS», «… EXCEPTO LG CHEM, LTD.»: en cualquier punto.
_RESIDUAL = re.compile(r"\bTODAS LAS (?:DEMÁS )?(?:EXPORTADORAS|EMPRESAS)\b")


class AnexoIlegibleError(ValueError):
    """El HTML no tiene la forma que este parser conoce. Mejor parar que cargar
    una tabla desalineada."""


@dataclass(frozen=True)
class Resolucion:
    tipo: str
    fecha: date


@dataclass(frozen=True)
class ParsedListing:
    product_description: str
    fraction_code: str
    origin_country: str
    exporter_text: str | None
    applies_to_all_others: bool
    duty_text: str
    #: El texto que el anexo pone en la columna de cuota ANTES de cualquier
    #: exportador: el alcance o la condición del registro entero («Tubería … en
    #: diámetros exteriores mayores …», «No se imponen cuotas … a …»).
    scope_note: str | None
    resolution_history: tuple[Resolucion, ...]

    @property
    def latest_resolution_date(self) -> date | None:
        return max((r.fecha for r in self.resolution_history), default=None)

    @property
    def first_resolution_date(self) -> date | None:
        """La resolución que originó la cuota. Distingue dos cuotas distintas
        sobre la misma fracción y origen: la tubería sin costura de China tiene
        una de 2011 y otra de 2014, para diámetros distintos."""
        return min((r.fecha for r in self.resolution_history), default=None)


# ── HTML → cuadrícula ────────────────────────────────────────────────────────


@dataclass
class _Celda:
    partes: list[str] = field(default_factory=list)
    filas: int = 1
    columnas: int = 1

    @property
    def texto(self) -> str:
        crudo = re.sub(r"[ \t\xa0]+", " ", "".join(self.partes))
        return "\n".join(linea.strip() for linea in crudo.split("\n") if linea.strip())


class _Tablas(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tablas: list[list[list[_Celda]]] = []
        self._pila: list[list[list[_Celda]]] = []
        self._celda: _Celda | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table":
            self._pila.append([])
        elif tag == "tr" and self._pila:
            self._pila[-1].append([])
        elif tag in ("td", "th") and self._pila and self._pila[-1]:
            self._celda = _Celda(
                filas=int(a.get("rowspan") or 1), columnas=int(a.get("colspan") or 1)
            )
        elif tag in ("br", "div", "p") and self._celda is not None:
            self._celda.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._celda is not None and self._pila:
            self._pila[-1][-1].append(self._celda)
            self._celda = None
        elif tag == "table" and self._pila:
            self.tablas.append(self._pila.pop())

    def handle_data(self, data: str) -> None:
        if self._celda is not None:
            self._celda.partes.append(data)


def _cuadricula(filas: list[list[_Celda]]) -> list[list[str]]:
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


def _es_encabezado(fila: list[str]) -> bool:
    return len(fila) == len(ENCABEZADO) and all(
        c.upper().startswith(e) for c, e in zip(fila, ENCABEZADO, strict=True)
    )


def filas_del_anexo(html: str) -> list[list[str]]:
    """Las filas del anexo, ya sin encabezados, de todas sus tablas seguidas.

    El anexo empieza en la tabla cuyo encabezado es el de `ENCABEZADO` y sigue
    en las tablas de seis columnas inmediatamente posteriores.
    """
    lector = _Tablas()
    lector.feed(html)
    cuadriculas = [_cuadricula(t) for t in lector.tablas]
    inicio = next((i for i, g in enumerate(cuadriculas) if g and _es_encabezado(g[0])), None)
    if inicio is None:
        raise AnexoIlegibleError("no se encontró la tabla con el encabezado del Anexo 2.5.1")
    filas: list[list[str]] = []
    for g in cuadriculas[inicio:]:
        if not g or any(len(f) != len(ENCABEZADO) for f in g):
            break
        filas.extend(f for f in g if not _es_encabezado(f))
    return filas


# ── Cuadrícula → registros ───────────────────────────────────────────────────


def _una_linea(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def paises_de(texto: str) -> list[str]:
    """«COREA EUA» → ["KR", "US"]. Un nombre que no está en `PAISES` para todo."""
    resto = _una_linea(texto).upper()
    codigos: list[str] = []
    for nombre in sorted(PAISES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(nombre)}\b", resto):
            codigos.append(PAISES[nombre])
            resto = re.sub(rf"\b{re.escape(nombre)}\b", " ", resto)
    if resto.strip() or not codigos:
        raise AnexoIlegibleError(f"país sin código ISO conocido: {texto!r}")
    return sorted(codigos)


def _resoluciones(texto: str) -> list[Resolucion]:
    salida: list[Resolucion] = []
    inicio = 0
    plano = _una_linea(texto)
    for m in _FECHA.finditer(plano):
        tipo = plano[inicio : m.start()].strip(" ;,")
        salida.append(Resolucion(tipo=tipo, fecha=date(int(m[3]), int(m[2]), int(m[1]))))
        inicio = m.end()
    return salida


@dataclass
class _Registro:
    producto: str
    fracciones: str
    pais: str
    fechas: list[str] = field(default_factory=list)
    pares: list[list[str]] = field(default_factory=list)
    alcance: list[str] = field(default_factory=list)


def _registros(filas: list[list[str]]) -> list[_Registro]:
    registros: list[_Registro] = []
    anterior = [""] * len(ENCABEZADO)
    for fila in filas:
        celdas = [c.strip() for c in fila]
        # Una página nueva repite vacías las tres primeras columnas del registro
        # que continúa.
        for k in range(3):
            if not celdas[k]:
                celdas[k] = anterior[k]
        producto, fracciones, pais, fecha, empresa, cuota = celdas
        if not registros or (producto, fracciones, pais) != (
            registros[-1].producto,
            registros[-1].fracciones,
            registros[-1].pais,
        ):
            registros.append(_Registro(producto, fracciones, pais))
        actual = registros[-1]
        if fecha and (not actual.fechas or actual.fechas[-1] != fecha):
            actual.fechas.append(fecha)
        if cuota:
            if not empresa and not actual.pares:
                if cuota not in actual.alcance:
                    actual.alcance.append(cuota)
            elif actual.pares and (not empresa or empresa == actual.pares[-1][0]):
                if cuota not in actual.pares[-1][1]:
                    actual.pares[-1][1] += "\n" + cuota
            elif not actual.pares or actual.pares[-1] != [empresa, cuota]:
                actual.pares.append([empresa, cuota])
        anterior = celdas
    return registros


def parse(html: str) -> list[ParsedListing]:
    """Una fila por fracción, país de origen y exportador del anexo."""
    salida: list[ParsedListing] = []
    for r in _registros(filas_del_anexo(html)):
        fracciones = ["".join(m.groups()) for m in _FRACCION.finditer(r.fracciones)]
        if not fracciones:
            raise AnexoIlegibleError(f"registro sin fracción: {r.producto!r}")
        if not r.pares:
            raise AnexoIlegibleError(f"registro sin cuota: {r.producto!r}")
        historial = tuple(res for f in r.fechas for res in _resoluciones(f))
        alcance = "\n".join(_una_linea(x) for x in r.alcance) or None
        for pais in paises_de(r.pais):
            for fraccion in dict.fromkeys(fracciones):
                for empresa, cuota in r.pares:
                    exportador = _una_linea(empresa) or None
                    salida.append(
                        ParsedListing(
                            product_description=_una_linea(r.producto),
                            fraction_code=fraccion,
                            origin_country=pais,
                            exporter_text=exportador,
                            applies_to_all_others=bool(
                                exportador and _RESIDUAL.search(exportador.upper())
                            ),
                            duty_text=_una_linea(cuota),
                            scope_note=alcance,
                            resolution_history=historial,
                        )
                    )
    return salida
