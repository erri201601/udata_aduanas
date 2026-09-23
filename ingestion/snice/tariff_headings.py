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
confiable ahí, sin ambigüedad de columnas.

SALTOS DE PÁGINA (2026-09-23)

Una fila puede cortarse exactamente en un salto de página -- la cola de su
descripción, sin ancla propia, sigue en la página siguiente. `_sin_huerfanas_iniciales`
reintenta la primera ancla real de cada página (o la fracción que la
antecede, ver `_PESO_POR_NIVEL`) quitándole esa cola huérfana. También puede
repetirse el encabezado "DESCRIPCIÓN" a media página cuando ahí mismo
empieza un capítulo nuevo -- `_headings_de_pagina` trata cada aparición como
el arranque de su propio segmento en vez de tomar sólo la última. Verificado
contra el documento completo: la prueba de aceptación de Persona 1 (todo
`heading`/`subheading` de `tariff_fractions` debe aparecer aquí) da 0 filas
faltantes tanto en partidas como en subpartidas.
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

#: Encabezado de subcapítulo ("SUBCAPÍTULO I"), seguido de un título en
#: mayúsculas de 1 a varias líneas ("ELEMENTOS QUÍMICOS"). Cae dentro del
#: rango de X de la columna DESCRIPCIÓN, igual que el texto real, y no tiene
#: ancla propia — sin filtrarlo, la partición global lo absorbe en la
#: primera partida que sigue, porque nada más lo reclama (regresión real,
#: hallazgo de Persona 1: partida 28.01 traía "SUBCAPÍTULO I ELEMENTOS
#: QUÍMICOS" pegado al frente de su descripción real).
_SUBCAPITULO_RE = re.compile(r"^SUBCAP[IÍ]TULO\s+[IVXLCDM]+$")

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


#: Cuántas líneas consecutivas se prueban por fila antes de rendirse.
#:
#: REGRESIÓN REAL (2026-09-23): con 8, la partida 03.04 ("Filetes y demás
#: carne de pescado...", que enumera especies de tilapias, bagres, salmones
#: etc. antes de sus subpartidas) necesita 15 líneas reales y la ventana ni
#: siquiera la consideraba como candidata. 24 deja margen sin dejar que un
#: error de conteo devore media página.
_MAX_LINEAS_POR_FILA = 24
#: Tolerancia para aceptar el conteo de líneas de una fila. Si ni siquiera la
#: mejor partición se acerca a esto, algo salió mal (falta una línea, ruido
#: sin filtrar) — mejor una fila con descripción vacía que una con texto
#: ajeno.
_TOLERANCIA_PT = 4.0


def _fin_de_oracion(lineas_texto: list[str]) -> list[bool]:
    """Si la línea `i` termina la primera oración de su fila (acaba en «.»).

    REGRESIÓN REAL (2026-09-23, hallazgo de Persona 1: la carga no cubría el
    100% de `tariff_fractions.heading`/`subheading`): un punto de abreviatura
    dentro de un nombre científico -- "Cichorium intybus var. foliosum)." en
    la subpartida 07.05.21, "var." termina en punto a mitad de frase -- no
    es fin de oración de verdad: la propia frase sigue en la línea
    siguiente, en minúscula ("foliosum)."). El punto sólo cuenta como fin de
    oración real si es la última línea o la que sigue empieza en mayúscula
    -- una oración nueva, en español, siempre arranca así.
    """
    m = len(lineas_texto)
    resultado = []
    for i, texto in enumerate(lineas_texto):
        termina = texto.rstrip().endswith(".")
        if termina and i + 1 < m:
            siguiente = lineas_texto[i + 1].lstrip()
            if siguiente and siguiente[0].islower():
                termina = False
        resultado.append(termina)
    return resultado


def _siguiente_fin_de_oracion(fin_oracion: list[bool]) -> list[int | None]:
    """`resultado[i]`: primer índice >= i que termina oración, o `None`."""
    m = len(fin_oracion)
    resultado: list[int | None] = [None] * (m + 1)
    siguiente: int | None = None
    for i in range(m - 1, -1, -1):
        if fin_oracion[i]:
            siguiente = i
        resultado[i] = siguiente
    return resultado


def _centro_de_fila(
    lineas_y: list[float], siguiente_fin: list[int | None], previo: int, n: int
) -> float:
    """El centro esperado de una fila de `n` líneas desde `previo`: mismo
    criterio que usa `_asignar_lineas` (ver su docstring) — promedio de Y
    sólo hasta la primera línea que termina oración dentro de la ventana."""
    limite = previo + n
    fin = siguiente_fin[previo]
    hasta = fin + 1 if fin is not None and fin < limite else limite
    return sum(lineas_y[previo:hasta]) / (hasta - previo)


#: Peso del error cuadrático de una fila en la DP, por nivel de su ancla.
#: Las fracciones (8) no se devuelven -- ni su texto ni su ajuste importan,
#: sólo que consuman el número correcto de líneas para no robárselas a la
#: partida/subpartida que sí importa. Con el mismo peso que partidas (4) y
#: subpartidas (6), la DP -que minimiza el error TOTAL de la página- podía
#: sacrificar el ajuste de una subpartida real con tal de ajustar mejor una
#: fracción irrelevante (regresión real: partida 39.20, página 381 -- la
#: fracción 3920.10.05 tiene una descripción larga y ambigua en cuántas
#: líneas ocupa, y la DP prefería una partición que la ajustaba casi
#: perfecto a costa de desalinear 39.20 misma y 3920.20, las dos con error
#: >11pt). Con las fracciones a peso casi cero, la DP ya no tiene motivo
#: para sacrificar nada por ellas -- consumen cuantas líneas hagan falta
#: para que la partida/subpartida siguiente ajuste, sin penalizar su propio
#: ajuste, que no se usa para nada.
_PESO_POR_NIVEL = {4: 1.0, 6: 1.0, 8: 0.001}


def _asignar_lineas(
    lineas_y: list[float], lineas_texto: list[str], anclas_y: list[float], niveles: list[int]
) -> list[int]:
    """Cuántas líneas consecutivas le tocan a cada ancla, en orden.

    REGRESIÓN REAL: probar esto voraz (fila por fila, de arriba a abajo, sin
    volver atrás) se desalinea en cuanto una fila adivina mal su número de
    líneas — y ninguna corrección posterior puede arreglarlo, porque el
    puntero ya avanzó de más o de menos. En la página real de prueba (61,
    prendas de vestir) una sola fila mal contada tumbó todas las que seguían
    en la misma página.

    Programación dinámica sobre TODA la página a la vez: `dp[i][j]` es el
    error mínimo (cuadrático, ponderado por `_PESO_POR_NIVEL`) de repartir
    las primeras `i` líneas entre las primeras `j` anclas, contiguo y en
    orden. Una fila mal ajustada en un punto no arrastra a las demás: el
    óptimo se calcula sobre el conjunto completo, no arrastrando una
    decisión anterior.

    REGRESIÓN REAL (2026-09-23, hallazgo de Persona 1: la carga no cubría el
    100% de `tariff_fractions.heading`/`subheading`): el código NO está
    centrado frente al promedio de TODAS las líneas de su fila — está
    centrado frente al promedio de sólo la PRIMERA ORACIÓN (hasta el primer
    «.»); lo que sigue después (una frase de enlace antes del listado de
    subpartidas, una enumeración larga de especies) no desplaza el centro.
    Verificado línea por línea contra el PDF real: partida 84.02 (6 líneas,
    la oración termina en la 5ª — "...agua sobrecalentada"." — y el ancla
    coincide con el promedio de esas 5, no de las 6, error 0.03 vs 5.49) y
    partida 03.04 (15 líneas, la oración termina en la 3ª — "...frescos,
    refrigerados o congelados." — y el ancla coincide con el promedio de
    esas 3, error 0.04 vs un desajuste de decenas de puntos que ni con
    ventana ampliada se acercaba). Sin líneas que terminen en «.» dentro de
    la ventana, se usa el promedio de todas — mismo comportamiento que antes
    para filas de una sola oración (la inmensa mayoría).
    """
    m, k = len(lineas_y), len(anclas_y)
    if k == 0:
        return []
    inf = float("inf")
    dp = [[inf] * (k + 1) for _ in range(m + 1)]
    eleccion = [[0] * (k + 1) for _ in range(m + 1)]
    # REGRESIÓN REAL (2026-09-23, probada y descartada): dejar libres TODAS
    # las líneas 0..i-1 antes de la primera ancla (`dp[i][0] = 0` para todo
    # `i`, no sólo `i=0`) para absorber el caso de una página que empieza a
    # media descripción de una fila cuya ancla vive en la página anterior
    # (p. ej. la fracción 0305.79.99, cuya enumeración de especies de atún
    # sigue en la página 54) rompió más de lo que arregló: le da a la
    # PRIMERA ancla libertad para terminar su fila en cualquier punto de la
    # página con error mínimo, y ese punto de corte deja de coincidir con el
    # principio real de la segunda ancla — la partida 03.06 de esa misma
    # página, que antes sólo fallaba ella sola, pasó a desalinear también a
    # las filas que la siguen. La partición entre páginas queda como deuda
    # documentada (ver docstring del módulo), no resuelta aquí.
    dp[0][0] = 0.0
    prefijo = [0.0]
    for y in lineas_y:
        prefijo.append(prefijo[-1] + y)
    siguiente_fin = _siguiente_fin_de_oracion(_fin_de_oracion(lineas_texto))

    for j in range(1, k + 1):
        for i in range(1, m + 1):
            mejor, mejor_n = inf, 1
            for n in range(1, min(_MAX_LINEAS_POR_FILA, i) + 1):
                previo = i - n
                if dp[previo][j - 1] == inf:
                    continue
                fin = siguiente_fin[previo]
                hasta = fin + 1 if fin is not None and fin < i else i
                promedio = (prefijo[hasta] - prefijo[previo]) / (hasta - previo)
                error = (promedio - anclas_y[j - 1]) ** 2 * _PESO_POR_NIVEL[niveles[j - 1]]
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


def _es_titulo_mayusculas(texto: str) -> bool:
    """Línea sin ninguna minúscula: título de subcapítulo, no texto legal.

    El cuerpo real (partidas, subpartidas) siempre está en minúsculas/frase
    normal en español; un título de subcapítulo es la única línea de la
    columna DESCRIPCIÓN enteramente en mayúsculas.
    """
    letras = [c for c in texto if c.isalpha()]
    return bool(letras) and all(c.isupper() for c in letras)


def _sin_subcapitulos(
    lineas_y: list[float], lineas_texto: list[str]
) -> tuple[list[float], list[str]]:
    """Quita "SUBCAPÍTULO N" y su título en mayúsculas (1+ líneas) de la página.

    Sin ancla propia, esas líneas quedarían pegadas a la primera
    partida/subpartida real que sigue (ver `_SUBCAPITULO_RE`).
    """
    y_filtradas: list[float] = []
    texto_filtrado: list[str] = []
    saltando_titulo = False
    for y, texto in zip(lineas_y, lineas_texto, strict=True):
        if _SUBCAPITULO_RE.match(texto.strip()):
            saltando_titulo = True
            continue
        if saltando_titulo:
            if _es_titulo_mayusculas(texto):
                continue
            saltando_titulo = False
        y_filtradas.append(y)
        texto_filtrado.append(texto)
    return y_filtradas, texto_filtrado


#: Cuántas líneas iniciales de una página se prueban como huérfanas antes de
#: rendirse. REGRESIÓN REAL (2026-09-23): la partida 84.80 (página 984)
#: traía pegados 17 líneas huérfanas -- la cola completa de la larguísima
#: lista de excepciones "Reconocibles como diseñadas exclusivamente para…"
#: de la partida anterior (84.79) --, la 03.06 (página 54) traía 26 -- la
#: cola de la enumeración de especies de atún de una fracción -- y la
#: subpartida 73.04.90 (página 798) traía 45 -- la página entera son tubos
#: de acero de la fracción anterior, y su propio contenido es una única
#: línea ("Los demás.") al final. 50 deja margen sin buscar indefinidamente.
_MAX_HUERFANAS_INICIALES = 50


def _sin_huerfanas_iniciales(
    lineas_y: list[float],
    lineas_texto: list[str],
    conteos: list[int],
    siguiente_fin: list[int | None],
    anclas: list[tuple[float, str, int]],
) -> tuple[list[float], list[str], list[int], list[int | None]]:
    """Reintenta la PRIMERA ancla de la página quitándole líneas iniciales.

    REGRESIÓN REAL (2026-09-23, hallazgo de Persona 1: la carga no cubría el
    100% de `tariff_fractions.heading`/`subheading`): una página puede
    empezar con la cola de la descripción de una fila cuyo código vive en la
    página ANTERIOR — sin ancla propia aquí, esas líneas se pegan a la
    primera ancla real y arruinan su centrado (verificado: partida 09.05 en
    la página 91 traía pegadas "Chile "ancho" o "anaheim"." y "Los demás.",
    la cola de la lista de chiles de la partida anterior; partida 84.80 en
    la página 984 traía pegada la cola —17 líneas— de la lista de
    excepciones de la partida 84.79).

    Las huérfanas, igual que cualquier descripción real, pueden ocupar
    varias líneas y varias oraciones -- no sólo una línea suelta -- así que
    los puntos de corte que se prueban son los que siguen a CADA línea que
    termina oración («.») o frase introductoria («:») dentro de las primeras
    `_MAX_HUERFANAS_INICIALES`, en orden creciente, no sólo 1/2/3 líneas
    sueltas. El «:» hace falta porque la cola huérfana puede terminar en una
    frase introductoria en vez de una oración (regresión real: subpartida
    03.02.21, página 30 -- la cola huérfana de la fila anterior termina en
    "...de las subpartidas 0302.91 a 0302.99:", sin punto).

    Se prueba SÓLO si la primera ancla que SÍ importa (partida o subpartida,
    no fracción -- ver `_PESO_POR_NIVEL`) ya falla la tolerancia con el
    reparto normal — una página que ya ajusta bien no se toca, así que esto
    no puede empeorar nada que ya funcionaba (regresión real: dejar que la
    propia DP decidiera libremente cuántas líneas saltarse, sin este
    candado, sí rompía filas que antes ajustaban bien más adelante en la
    misma página — intentado y revertido antes de este candado). Cada corte
    probado termina justo después de una oración completa -- nunca a mitad
    de una frase -- y se acepta el primero (el más corto) que hace ajustar
    esa ancla, así que no se descarta más de lo necesario.

    Cuando la PRIMERA ancla de la página es, a su vez, una fracción (nivel
    8) que ya venía arrastrando su propia cola huérfana de una página
    todavía anterior (regresión real: partida 03.06, página 54 -- la
    primera ancla es la fracción 0305.79.99, cuya propia enumeración de
    especies de atún sigue arrastrándose de la página 53), lo que importa no
    es el ajuste de esa fracción -- es el de la primera partida/subpartida
    real que sigue, así que el candado se prueba contra ÉSA, no contra
    `anclas[0]`.
    """
    idx_relevante = next((i for i, a in enumerate(anclas) if a[2] != 8), None)
    if idx_relevante is None or not conteos or any(c == 0 for c in conteos[: idx_relevante + 1]):
        return lineas_y, lineas_texto, conteos, siguiente_fin
    offset = sum(conteos[:idx_relevante])
    error_inicial = abs(
        _centro_de_fila(lineas_y, siguiente_fin, offset, conteos[idx_relevante])
        - anclas[idx_relevante][0]
    )
    if error_inicial <= _TOLERANCIA_PT:
        return lineas_y, lineas_texto, conteos, siguiente_fin

    limite = min(len(lineas_texto) - 1, _MAX_HUERFANAS_INICIALES)
    candidatos = (i + 1 for i in range(limite) if lineas_texto[i].rstrip().endswith((".", ":")))
    for corte in candidatos:
        y2, t2 = lineas_y[corte:], lineas_texto[corte:]
        conteos2 = _asignar_lineas(y2, t2, [a[0] for a in anclas], [a[2] for a in anclas])
        if not conteos2 or any(c == 0 for c in conteos2[: idx_relevante + 1]):
            continue
        fin2 = _siguiente_fin_de_oracion(_fin_de_oracion(t2))
        offset2 = sum(conteos2[:idx_relevante])
        error2 = abs(
            _centro_de_fila(y2, fin2, offset2, conteos2[idx_relevante]) - anclas[idx_relevante][0]
        )
        if error2 <= _TOLERANCIA_PT:
            return y2, t2, conteos2, fin2
    return lineas_y, lineas_texto, conteos, siguiente_fin


def _headings_de_pagina(palabras: list[_Palabra]) -> list[tuple[str, int, str]]:
    """(code, level, description) de las partidas/subpartidas de una página.

    Las fracciones (nivel 8) sólo sirven aquí como ancla -- consumen sus
    propias líneas para que la fila siguiente no las herede -- nunca se
    devuelven: esas ya se cargan del XLSX.
    """
    y_encabezados = sorted(p.y for p in palabras if _ENCABEZADO_RE.match(p.texto))
    y_pie = min((p.y for p in palabras if _PIE_RE.match(p.texto)), default=float("inf"))

    # REGRESIÓN REAL (2026-09-23, hallazgo de Persona 1: la carga no cubría
    # el 100% de `tariff_fractions.heading`/`subheading`): cuando un
    # capítulo nuevo empieza a media página (p. ej. el capítulo 81 arranca
    # a mitad de la página 848, justo debajo de donde termina el 80), la
    # tabla reimprime el encabezado "DESCRIPCIÓN" -- la página trae DOS, no
    # uno. Tomar el último con `max()` trataba TODO lo de arriba del segundo
    # como si aún fuera encabezado institucional, y las partidas 80.03 y
    # 80.07 (que sí tienen su propio código a la izquierda, ahí arriba)
    # quedaban fuera del rango de Y por completo -- ni siquiera llegaban a
    # candidatas a ancla. Cada encabezado ahora abre su propio segmento,
    # acotado por el SIGUIENTE encabezado (o el pie de página si es el
    # último), y cada segmento se resuelve por separado.
    segmentos = [
        (y_encabezados[idx], y_encabezados[idx + 1] if idx + 1 < len(y_encabezados) else y_pie)
        for idx in range(len(y_encabezados))
    ] or [(float("-inf"), y_pie)]

    resultado: list[tuple[str, int, str]] = []
    for y_min, y_max in segmentos:
        # El código se guarda SIN el punto ("8401" no "84.01"): mismo
        # convenio que `tariff_fractions.code`
        # (`ingestion.snice.tariff._split_code`), y lo que exige el CHECK
        # `length(code) = level` de la migración -- con el punto, "84.01"
        # mide 5, no 4, y toda fila reventaría la restricción (regresión
        # real, encontrada al probar la carga contra Postgres).
        anclas: list[tuple[float, str, int]] = []
        for p in palabras:
            if p.x >= X_CODIGO_MAX or not (y_min < p.y < y_max):
                continue
            if _FRACCION_RE.match(p.texto):
                anclas.append((p.y, p.texto.replace(".", ""), 8))
            elif _SUBPARTIDA_RE.match(p.texto):
                anclas.append((p.y, p.texto.replace(".", ""), 6))
            elif _PARTIDA_RE.match(p.texto):
                anclas.append((p.y, p.texto.replace(".", ""), 4))
        anclas.sort(key=lambda a: a[0])
        if not anclas:
            continue

        lineas_y, lineas_texto = _sin_subcapitulos(
            _y_de_lineas(palabras, y_min, y_max), _lineas_de_descripcion(palabras, y_min, y_max)
        )
        conteos = _asignar_lineas(
            lineas_y, lineas_texto, [a[0] for a in anclas], [a[2] for a in anclas]
        )
        siguiente_fin = _siguiente_fin_de_oracion(_fin_de_oracion(lineas_texto))

        lineas_y, lineas_texto, conteos, siguiente_fin = _sin_huerfanas_iniciales(
            lineas_y, lineas_texto, conteos, siguiente_fin, anclas
        )

        idx = 0
        for (y_code, code, level), n in zip(anclas, conteos, strict=True):
            # El puntero SIEMPRE avanza según la partición global de
            # `_asignar_lineas`, se reporte o no esta fila: es una
            # partición completa del segmento, no una decisión por fila.
            # Rechazar el texto de una fila puntual no puede desalinear
            # las que siguen (regresión real: hacerlo así tumbaba toda la
            # página después del primer rechazo).
            confiable = n > 0 and abs(
                _centro_de_fila(lineas_y, siguiente_fin, idx, n) - y_code
            ) <= (_TOLERANCIA_PT)
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
