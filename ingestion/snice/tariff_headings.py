"""PARSED de partidas (4 dígitos) y subpartidas (6) de la LIGIE (ADR 0002).

Por qué existe: la descripción de una fracción no se sostiene sola —«De
acero inoxidable.» no dice de qué—, y el sujeto vive en el texto de la
partida o subpartida, que hoy no está en ninguna columna de la base. Ver
`docs/adr/0002-donde-vive-el-texto-de-partidas-y-subpartidas.md`.

POR QUÉ `pdftotext -layout` NO BASTA (y `-bbox-layout` sí)

En la tabla de fracciones, el código de una partida/subpartida queda
verticalmente CENTRADO frente a su descripción cuando ésta ocupa más de una
línea — artefacto real de cómo el DOF maqueta la columna angosta de código
junto a la ancha de descripción. Con `pdftotext -layout` (texto plano, sin
coordenadas), el código aparece INTERCALADO a la mitad de su propia
descripción de 4 líneas: la mitad del texto queda antes, la mitad después,
en el flujo de líneas. Un parser de líneas (como
`ingestion.diputados.ley_aduanera`) le pegaría media descripción a la fila
anterior. Verificado con una página real (partida 84.01, "Reactores
nucleares...") y confirmado en un capítulo distinto (61, prendas de vestir):
mismo patrón, mismas coordenadas de columna.

`pdftotext -bbox-layout` da la posición (x, y) de cada palabra.

REGRESIÓN REAL: el punto medio entre código vecino y código vecino NO
sirve. Se probó primero así, y con 84.01 (4 líneas) seguido de 8401.10 (1
línea sola) el punto medio quedaba MÁS ARRIBA que la última línea real de
84.01 — le robaba su propia última línea a la fila siguiente. El punto
medio asume que las dos filas vecinas tienen más o menos el mismo número de
líneas, y esa fila real que lo desmiente está en la primera página que se
probó, no en un caso raro.

Lo que sí sostiene la geometría (verificado con las líneas reales, no una
suposición): dentro de una fila el código está centrado — Y_código es el
promedio de las Y de sus propias líneas de descripción — y las filas son
CONTIGUAS: no hay hueco entre el final de una y el principio de la
siguiente en la lista de líneas del documento. Con eso, cada fila se
resuelve por conteo: desde el puntero de línea actual, se prueba cuántas
líneas consecutivas (1, 2, 3…) hacen que su promedio coincida con Y_código,
se consumen esas líneas, y el puntero avanza — nunca se retrocede.

Columnas verificadas contra el PDF real (dos capítulos distintos, mismas
coordenadas en los dos): CÓDIGO en x<130, NICO/SUBP en x≈140-152,
DESCRIPCIÓN en 155<=x<360, UMT (Kg/Pza/...) en x>=363. El ruido
institucional que se repite en cada página ("Dirección General de
Facilitación Comercial y de Comercio Exterior", encabezados de columna) cae
DENTRO del rango de X de la columna de descripción — filtrarlo por
contenido de palabra falla porque trae conectores comunes ("de", "y") que
también aparecen en texto real. Se filtra por posición Y en su lugar: todo
lo que esté en o antes del encabezado "DESCRIPCIÓN" de esa página, o en o
después del pie de página ("Calle Pachuca…"), no es tabla.

QUÉ NO HACE

Sólo extrae partida (4 dígitos) y subpartida (6): las fracciones (8) ya se
cargan de la hoja `FA` del XLSX de SNICE (`ingestion.snice.tariff`) — más
confiable ahí, sin ambigüedad de columnas. No cruza páginas: una descripción
que se corte exactamente en un salto de página queda incompleta — no se
detectó ningún caso real al validar, pero es deuda documentada, no un caso
resuelto.
"""

from __future__ import annotations

import html
import re
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Ancla del encabezado de columna: todo lo que esté EN o ANTES de esta Y es
#: el encabezado institucional de la página ("Dirección General de
#: Facilitación Comercial y de Comercio Exterior"), no tabla.
_ENCABEZADO_RE = re.compile(r"^DESCRIPCI[ÓO]N$")
#: Ancla del pie de página: todo lo que esté EN o DESPUÉS de esta Y es el
#: pie institucional ("Calle Pachuca #189…"), no tabla.
_PIE_RE = re.compile(r"^Pachuca$")

_PARTIDA_RE = re.compile(r"^\d{2}\.\d{2}$")
_SUBPARTIDA_RE = re.compile(r"^\d{4}\.\d{2}$")
_FRACCION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")

#: Límites de columna, verificados contra el PDF real en dos capítulos
#: distintos (84 y 61) con `pdftotext -bbox-layout` — ver docstring del
#: módulo.
X_CODIGO_MAX = 130.0
X_DESCRIPCION_MIN = 155.0
X_DESCRIPCION_MAX = 360.0

_WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">([^<]*)</word>'
)


@dataclass(frozen=True)
class _Palabra:
    x: float
    y: float
    texto: str


@dataclass(frozen=True)
class ParsedHeading:
    code: str
    level: int  # 4 o 6
    chapter: str
    description: str


def _palabras_de(bbox_xml: str) -> list[_Palabra]:
    return [
        _Palabra(float(x), float(y), html.unescape(t)) for x, y, t in _WORD_RE.findall(bbox_xml)
    ]


def extract_bbox_pages(
    pdf_path: str, *, first_page: int = 1, last_page: int | None = None
) -> Iterator[tuple[int, str]]:
    """(número de página, XML de `pdftotext -bbox-layout`), una llamada por página.

    Una llamada a `pdftotext` por página (no todo el documento de una vez):
    el XML de bbox de las ~1,300 páginas de la LIGIE completa no cabe
    cómodo en memoria de una sola pasada, y así se puede reanudar por rango
    si algo falla a medio documento.
    """
    if last_page is None:
        info = subprocess.run(["pdfinfo", pdf_path], capture_output=True, check=True, text=True)
        m = re.search(r"^Pages:\s+(\d+)", info.stdout, re.MULTILINE)
        if not m:
            raise ValueError(f"pdfinfo no reportó el número de páginas de {pdf_path!r}")
        last_page = int(m.group(1))

    for pagina in range(first_page, last_page + 1):
        resultado = subprocess.run(
            ["pdftotext", "-bbox-layout", "-f", str(pagina), "-l", str(pagina), pdf_path, "-"],
            capture_output=True,
            check=True,
            text=True,
        )
        yield pagina, resultado.stdout


#: Cuántas líneas consecutivas se prueban por fila antes de rendirse. Ninguna
#: descripción real vista al validar pasó de 4; 8 deja margen sin permitir
#: que un error de conteo devore media página.
_MAX_LINEAS_POR_FILA = 8
#: Tolerancia para aceptar el conteo de líneas de una fila. Si ni siquiera la
#: mejor partición se acerca a esto, algo salió mal (falta una línea, ruido
#: sin filtrar) — mejor una fila con descripción vacía que una con texto
#: ajeno.
_TOLERANCIA_PT = 4.0


def _asignar_lineas(lineas_y: list[float], anclas_y: list[float]) -> list[int]:
    """Cuántas líneas consecutivas le tocan a cada ancla, en orden.

    REGRESIÓN REAL: probar esto voraz (fila por fila, de arriba a abajo, sin
    volver atrás) se desalinea en cuanto una fila adivina mal su número de
    líneas — y ninguna corrección posterior puede arreglarlo, porque el
    puntero ya avanzó de más o de menos. En la página real de prueba (61,
    prendas de vestir) una sola fila mal contada tumbó todas las que seguían
    en la misma página.

    Programación dinámica sobre TODA la página a la vez: `dp[i][j]` es el
    error mínimo (cuadrático) de repartir las primeras `i` líneas entre las
    primeras `j` anclas, contiguo y en orden. Una fila mal ajustada en un
    punto no arrastra a las demás: el óptimo se calcula sobre el conjunto
    completo, no arrastrando una decisión anterior.
    """
    m, k = len(lineas_y), len(anclas_y)
    if k == 0:
        return []
    inf = float("inf")
    dp = [[inf] * (k + 1) for _ in range(m + 1)]
    eleccion = [[0] * (k + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    prefijo = [0.0]
    for y in lineas_y:
        prefijo.append(prefijo[-1] + y)

    for j in range(1, k + 1):
        for i in range(1, m + 1):
            mejor, mejor_n = inf, 1
            for n in range(1, min(_MAX_LINEAS_POR_FILA, i) + 1):
                previo = i - n
                if dp[previo][j - 1] == inf:
                    continue
                promedio = (prefijo[i] - prefijo[previo]) / n
                error = (promedio - anclas_y[j - 1]) ** 2
                total = dp[previo][j - 1] + error
                if total < mejor:
                    mejor, mejor_n = total, n
            dp[i][j] = mejor
            eleccion[i][j] = mejor_n

    # Reconstrucción: si dp[m][k] no es alcanzable (más anclas que líneas
    # posibles, p. ej. una página que empieza a mitad de un salto), se
    # reparte lo que haya con el mejor ajuste encontrado en la última fila
    # alcanzable en vez de fallar toda la página.
    i_final = m if dp[m][k] < inf else max((i for i in range(m + 1) if dp[i][k] < inf), default=0)
    conteos = [0] * k
    i, j = i_final, k
    while j > 0 and i > 0:
        n = eleccion[i][j]
        conteos[j - 1] = n
        i -= n
        j -= 1
    return conteos


def _lineas_de_descripcion(palabras: list[_Palabra], y_min: float, y_max: float) -> list[str]:
    """Líneas de la columna DESCRIPCIÓN, en orden, ya sin encabezado ni pie.

    Agrupa por Y exacta: en este documento, las palabras de una misma línea
    comparten la misma `yMin` (verificado contra el PDF real) — no hace
    falta una tolerancia de clustering.
    """
    por_y: dict[float, list[_Palabra]] = {}
    for p in palabras:
        if X_DESCRIPCION_MIN <= p.x < X_DESCRIPCION_MAX and y_min < p.y < y_max:
            por_y.setdefault(p.y, []).append(p)
    lineas = []
    for y in sorted(por_y):
        palabras_linea = sorted(por_y[y], key=lambda p: p.x)
        lineas.append(" ".join(p.texto for p in palabras_linea))
    return lineas


def _y_de_lineas(palabras: list[_Palabra], y_min: float, y_max: float) -> list[float]:
    ys = {
        p.y
        for p in palabras
        if X_DESCRIPCION_MIN <= p.x < X_DESCRIPCION_MAX and y_min < p.y < y_max
    }
    return sorted(ys)


def _headings_de_pagina(palabras: list[_Palabra]) -> list[tuple[str, int, str]]:
    """(code, level, description) de las partidas/subpartidas de una página.

    Las fracciones (nivel 8) sólo sirven aquí como ancla -- consumen sus
    propias líneas para que la fila siguiente no las herede -- nunca se
    devuelven: esas ya se cargan del XLSX.
    """
    y_encabezado = max((p.y for p in palabras if _ENCABEZADO_RE.match(p.texto)), default=None)
    y_pie = min((p.y for p in palabras if _PIE_RE.match(p.texto)), default=None)
    y_min = y_encabezado if y_encabezado is not None else float("-inf")
    y_max = y_pie if y_pie is not None else float("inf")

    anclas: list[tuple[float, str, int]] = []
    for p in palabras:
        if p.x >= X_CODIGO_MAX or not (y_min < p.y < y_max):
            continue
        if _FRACCION_RE.match(p.texto):
            anclas.append((p.y, p.texto, 8))
        elif _SUBPARTIDA_RE.match(p.texto):
            anclas.append((p.y, p.texto, 6))
        elif _PARTIDA_RE.match(p.texto):
            anclas.append((p.y, p.texto, 4))
    anclas.sort(key=lambda a: a[0])

    lineas_y = _y_de_lineas(palabras, y_min, y_max)
    lineas_texto = _lineas_de_descripcion(palabras, y_min, y_max)
    conteos = _asignar_lineas(lineas_y, [a[0] for a in anclas])

    resultado: list[tuple[str, int, str]] = []
    idx = 0
    for (y_code, code, level), n in zip(anclas, conteos, strict=True):
        # El puntero SIEMPRE avanza según la partición global de
        # `_asignar_lineas`, se reporte o no esta fila: es una partición
        # completa de la página, no una decisión por fila. Rechazar el
        # texto de una fila puntual no puede desalinear las que siguen
        # (regresión real: hacerlo así tumbaba toda la página después del
        # primer rechazo).
        confiable = n > 0 and abs(sum(lineas_y[idx : idx + n]) / n - y_code) <= _TOLERANCIA_PT
        if level != 8 and confiable:
            texto = " ".join(lineas_texto[idx : idx + n]).strip()
            texto = " ".join(texto.split())
            if texto:
                resultado.append((code, level, texto))
        idx += n
    return resultado


def parse_headings(
    pdf_path: str, *, first_page: int = 1, last_page: int | None = None
) -> list[ParsedHeading]:
    """Todas las partidas/subpartidas de la LIGIE, RAW (PDF) -> PARSED.

    Un código puede aparecer más de una vez en el documento (p. ej. un
    índice al inicio, o una referencia cruzada en una nota). Gana la
    PRIMERA aparición -- mismo criterio que
    `ingestion.dof.rgce.parse_transitorios` con el segundo bloque de
    ordinales duplicado: la tabla real siempre precede a cualquier
    referencia posterior en el documento.
    """
    encontrados: dict[str, ParsedHeading] = {}
    for _, bbox_xml in extract_bbox_pages(pdf_path, first_page=first_page, last_page=last_page):
        palabras = _palabras_de(bbox_xml)
        for code, level, texto in _headings_de_pagina(palabras):
            encontrados.setdefault(
                code, ParsedHeading(code=code, level=level, chapter=code[:2], description=texto)
            )
    return sorted(encontrados.values(), key=lambda h: h.code)
