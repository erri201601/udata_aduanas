"""RAW -> PARSED del Anexo 22 (Instructivo para el llenado del pedimento).

Fuente: RGCE 2026, publicado en el DOF el 15-ene-2026. Este módulo cubre los
5 catálogos de referencia: aduanas/secciones, unidades de medida, claves de
pedimento, identificadores de regulaciones no arancelarias (Apéndice 9) e
identificadores de pedimento (Apéndice 8, código + nivel -- Persona 1,
2026-09-29). El resto (el texto legal de cada clave de pedimento y de cada
identificador, y la correlación fracción -> NOM, que este documento no trae)
queda como deuda documentada.

`pdftotext -layout` linealiza el PDF en texto plano intentando conservar las
columnas por posición de caracter. Funciona sin pérdida quando cada fila usa
una sola columna de texto (Apéndices 1, 7 y 9). Falla en el Apéndice 2: ahí
la etiqueta de la clave y la lista de "supuestos de aplicación" son dos
columnas visuales lado a lado, y se intercalan en el mismo renglón sin ningún
separador de caracteres fiable — por eso `parse_pedimento_claves` solo extrae
`code`, nunca `label` (ver el docstring de `PedimentoClave` en
`database/models/regulatory.py`).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

# Reuso deliberado del motor de reparto por programación dinámica de
# `ingestion.snice.tariff_headings` (genérico: ancla por código, reparte
# líneas de una columna de texto por posición X real) para
# `parse_identifiers_con_texto` más abajo -- la misma ambigüedad de columnas
# que dejó `PedimentoClave.label`/`supuestos_de_aplicacion` sin cargar, pero
# aquí SÍ se resuelve, con la misma herramienta que ya resolvió el ADR 0004.
# No se copia el código: duplicar ~150 líneas de DP ya probadas es peor que
# esta dependencia cruzada entre dos módulos de `ingestion`.
from ingestion.snice.tariff_headings import (
    _Palabra,
    _palabras_de,
    extract_bbox_pages,
)

# ── extracción de texto ─────────────────────────────────────────────────────


def extract_text(pdf_path: str) -> list[str]:
    """`pdftotext -layout` sobre el PDF ya descargado. Devuelve las líneas tal cual.

    `-layout` es el modo que preserva la posición horizontal del texto —
    indispensable para distinguir código/continuación por sangría (ver los
    parsers de abajo). Sin él, `pdftotext` reflowea el texto y esa señal
    desaparece.
    """
    resultado = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True,
        check=True,
        text=True,
    )
    return resultado.stdout.splitlines(keepends=True)


_HEADING_RE = re.compile(r"^\s*Apéndice\s+(\d{1,2})\s*(?:\d{1,4})?\s*$")


def find_appendix_headings(lines: list[str]) -> dict[int, int]:
    """Índice (0-based) de la primera línea de cada "Apéndice N" del documento.

    Localizar por búsqueda de encabezado, no por número de línea fijo: si el
    documento se vuelve a extraer (otra versión de `pdftotext`, otra corrida),
    los límites se recalculan solos en vez de apuntar a texto que ya no está
    ahí. Sólo la PRIMERA aparición de cada número cuenta como encabezado real
    — el Apéndice 6 aparece dos veces en el documento real; usamos la primera,
    que es su encabezado propio.
    """
    headings: dict[int, int] = {}
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line.rstrip("\n"))
        if m:
            n = int(m.group(1))
            headings.setdefault(n, i)
    return headings


def appendix_block(lines: list[str], headings: dict[int, int], n: int) -> list[str]:
    """Líneas entre el encabezado del Apéndice `n` y el siguiente encabezado detectado.

    Excluye la propia línea "Apéndice N": si no, un parser que trata cualquier
    línea sin sangría de código como nombre de dependencia/sección (p. ej.
    `parse_non_tariff_regulations`) la concatena al primer encabezado real.
    """
    if n not in headings:
        raise RuntimeError(
            f"Apéndice {n} no encontrado en el texto extraído — el documento "
            "cambió de estructura. No se adivina el rango (regla del §5 "
            "CLAUDE.md: falla ruidoso ante estructura inesperada)."
        )
    start = headings[n]
    siguientes = sorted(idx for num, idx in headings.items() if idx > start)
    end = siguientes[0] if siguientes else len(lines)
    return lines[start + 1 : end]


def paginas_de_apendice(pdf_path: str, n: int) -> tuple[int, int]:
    """Páginas físicas (1-based, inclusive) donde vive el Apéndice `n`.

    `parse_identifiers_con_texto`/`extract_bbox_pages` sólo saben de páginas
    bbox, no de líneas de `-layout` -- quien los llama necesita convertir.
    Localiza por encabezado real (mismo criterio que `find_appendix_headings`:
    si el documento cambia de edición, el rango se recalcula solo), no por
    número de página fijo. `extract_text()` no sirve para esto: `splitlines()`
    también parte en el salto de página (`\\x0c`), así que esa frontera se
    pierde -- por eso aquí se corre `pdftotext` aparte, sobre el `stdout`
    crudo.

    Nota real de implementación: NO se puede partir `stdout` por `\\x0c` y
    luego contar líneas página por página -- se probó y da un número de
    línea GLOBAL distinto al que usa `find_appendix_headings` (`\\x0c` en
    medio de texto también cuenta como línea propia para `splitlines()`,
    y se pierde al partir antes). Por eso aquí se camina `stdout` una sola
    vez con `splitlines(keepends=True)` (mismo corte exacto, índice a
    índice, que el `lines` de `find_appendix_headings`) y se cuenta un
    salto de página cada vez que una "línea" termina en `\\x0c`.
    """
    resultado = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"], capture_output=True, check=True, text=True
    )
    lines = resultado.stdout.splitlines()
    headings = find_appendix_headings(lines)
    if n not in headings:
        raise RuntimeError(
            f"Apéndice {n} no encontrado en el texto extraído — no se calculan "
            "páginas sin saber dónde empieza (regla del §5 CLAUDE.md)."
        )
    start = headings[n]
    siguientes = sorted(idx for num, idx in headings.items() if idx > start)

    pagina_de_linea: list[int] = []
    pagina_actual = 1
    for parte in resultado.stdout.splitlines(keepends=True):
        pagina_de_linea.append(pagina_actual)
        if parte.endswith("\x0c"):
            pagina_actual += 1

    first_page = pagina_de_linea[start]
    # La página del SIGUIENTE encabezado se excluye COMPLETA, no sólo desde
    # su línea -- verificado contra el documento real: la 198 (Apéndice 9)
    # no trae ninguna fila del Apéndice 8 antes de su encabezado, sólo el
    # pie de página repetido ("DIARIO OFICIAL..."). `extract_bbox_pages`
    # sólo sabe pedir páginas enteras -- a diferencia de `appendix_block`,
    # que sí puede cortar a mitad de página por línea, aquí no hay forma de
    # pedir "hasta la línea end-1" sin arrastrar el resto de esa página.
    last_page = pagina_de_linea[siguientes[0]] - 1 if siguientes else pagina_de_linea[-1]
    return first_page, last_page


_NOISE_RE = re.compile(
    r"DIARIO OFICIAL|^\s*\d{1,3}\s*$|Jueves|Viernes|Lunes|Martes|Mi[eé]rcoles|S[aá]bado|Domingo",
)


# ── Apéndice 1: Aduana - Sección ────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedCustomsOffice:
    aduana: str
    seccion: str | None
    name: str


_ADUANA_RE = re.compile(r"^\s*(\d{2})\s+(?:(\d{1,2})\s+)?(\S.*)$")


def parse_customs_offices(lines: list[str]) -> list[ParsedCustomsOffice]:
    """Apéndice 1: aduana (2 dígitos) + sección (0-N, puede faltar) + denominación.

    `seccion` queda en `None` cuando el DOF no le asigna número a esa
    instalación (p. ej. anexos/satélites de una aduana base) — es la
    estructura real del documento, no un hueco de parseo (verificado a mano
    contra el PDF, aduana 17/Matamoros entre otras).
    """
    filas: list[ParsedCustomsOffice] = []
    aduana: str | None = None
    seccion: str | None = None
    name: str | None = None

    def flush() -> None:
        if aduana is not None and name is not None:
            filas.append(ParsedCustomsOffice(aduana=aduana, seccion=seccion, name=name))

    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or _NOISE_RE.search(line):
            continue
        m = _ADUANA_RE.match(line)
        if m:
            flush()
            aduana, seccion, name = m.group(1), m.group(2), m.group(3).strip()
        elif name is not None:
            name = f"{name} {line.strip()}"
    flush()
    return filas


# ── Apéndice 7: Unidades de medida ──────────────────────────────────────────


@dataclass(frozen=True)
class ParsedUnitOfMeasure:
    code: str
    description: str


_UNIDAD_RE = re.compile(r"^\s*(\d{1,2})\s+(\S.*)$")


def parse_units_of_measure(lines: list[str]) -> list[ParsedUnitOfMeasure]:
    """Apéndice 7: tabla trivial de 2 columnas, una fila por línea, sin envolturas."""
    filas: list[ParsedUnitOfMeasure] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or _NOISE_RE.search(line) or "Clave" in line:
            continue
        m = _UNIDAD_RE.match(line)
        if m:
            filas.append(ParsedUnitOfMeasure(code=m.group(1), description=m.group(2).strip()))
    return filas


# ── Apéndice 2: Claves de pedimento (solo código — ver docstring del módulo) ─


@dataclass(frozen=True)
class ParsedPedimentoClave:
    code: str


# Exige espacio a AMBOS lados del guión: descarta falsos positivos como
# "T-MEC" (sin espacios) que de otro modo se leerían como la clave "T".
_CLAVE_RE = re.compile(r"^\s*([A-Z][0-9A-Z]{1,2})\s+-\s+(\S.*)$")


def parse_pedimento_claves(lines: list[str]) -> list[ParsedPedimentoClave]:
    """Apéndice 2: solo el código. La etiqueta y los supuestos no se extraen aquí.

    Se probó separar la etiqueta con una guarda de numeral romano (el punto
    de "I." leído como fin de oración) y no bastó: el layout de 2 columnas
    del PDF mezcla texto de la lista de supuestos en la MISMA línea que la
    etiqueta incluso sin numeral visible (casos reales: T1, VF, G9, V6, V7,
    V9, AD, BD, BE, BI, BP, BR — verificado línea por línea contra el PDF).
    Cargar esas etiquetas habría puesto prosa corrupta en una tabla marcada
    `OFFICIAL` sin que se notara — exactamente el tipo de error que Persona 1
    señaló como el peor que puede tener este sistema.
    """
    codigos: list[str] = []
    vistos: set[str] = set()
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        m = _CLAVE_RE.match(line)
        if m:
            code = m.group(1)
            if code not in vistos:
                vistos.add(code)
                codigos.append(code)
    return [ParsedPedimentoClave(code=c) for c in codigos]


# ── Apéndice 9: Identificadores / regulaciones no arancelarias ─────────────


@dataclass(frozen=True)
class ParsedNonTariffRegulation:
    code: str
    issuing_agency: str
    description: str


_IDENTIFICADOR_RE = re.compile(r"^ ([A-Z][A-Z0-9])\s{2,}(\S.*)$")
_TABLE_HEADER_RE = re.compile(r"^\s*Clave\s+Descripci[oó]n", re.IGNORECASE)
# Subtítulo del propio Apéndice 9, no el nombre de una dependencia. Sin este
# filtro se pega al frente del primer nombre real ("Secretaría de Economía")
# porque no hay "Clave Descripción" entre ambos que corte el encabezado.
_APPENDIX_SUBTITLE_RE = re.compile(r"^Regulaciones y restricciones no arancelarias$", re.IGNORECASE)


def parse_non_tariff_regulations(lines: list[str]) -> list[ParsedNonTariffRegulation]:
    """Apéndice 9: código + dependencia emisora + descripción completa.

    Layout de una sola columna (a diferencia del Apéndice 2): la sangría es
    la única señal necesaria. Una entrada nueva empieza en columna 1 (código
    de 2 caracteres); su continuación va en columna 9 (margen fijo del
    párrafo); cualquier otra cosa —sangría mayor, centrada— es el nombre de
    la dependencia que agrupa las entradas siguientes.

    `code` se repite entre dependencias con significados distintos —
    confirmado en el documento real ("C1"/"C6" existen tanto bajo Secretaría
    de Economía como bajo Secretaría de Energía) — por eso la llave natural
    de la tabla es `(code, issuing_agency)`, nunca `code` solo.
    """
    filas: list[ParsedNonTariffRegulation] = []
    current_section_parts: list[str] = []
    in_header = False
    buffer_code: str | None = None
    buffer_text: list[str] = []

    def flush() -> None:
        nonlocal buffer_code, buffer_text
        if buffer_code is not None:
            descripcion = " ".join(t.strip() for t in buffer_text if t.strip())
            filas.append(
                ParsedNonTariffRegulation(
                    code=buffer_code,
                    issuing_agency=" ".join(current_section_parts) or "?",
                    description=descripcion,
                )
            )
        buffer_code = None
        buffer_text = []

    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if _TABLE_HEADER_RE.match(line) or _NOISE_RE.search(line):
            in_header = False
            continue
        if _APPENDIX_SUBTITLE_RE.match(line.strip()):
            continue
        indent = len(line) - len(line.lstrip(" "))
        m = _IDENTIFICADOR_RE.match(line)
        if m and indent == 1:
            flush()
            buffer_code = m.group(1)
            buffer_text = [m.group(2)]
            continue
        if indent == 8 and buffer_code is not None:
            buffer_text.append(line)
            continue
        if not in_header:
            flush()
            current_section_parts = []
            in_header = True
        current_section_parts.append(line.strip())

    flush()
    return filas


# ── Apéndice 8: Identificadores ──────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedIdentifier:
    code: str
    level: str | None
    label: str | None = None
    supuestos_de_aplicacion: str | None = None


# Exige el guión: sin él, un numeral romano jerárquico dentro de un
# "Complemento" ("III.   Procedimientos...") calzaría igual que un código real
# (regresión real: "II" -- código legítimo, "Inventario inicial de..." -- y
# "III." -- numeral, no código -- sólo se distinguen por esto).
#
# "-" (guión) o "–" (guión largo, U+2013): el documento real NO es
# consistente -- regresión real encontrada el 2026-10-06, extrayendo
# `label`/`supuestos_de_aplicacion` por coordenadas: CR, EO, PB y PO usan
# guión largo ("EO – Emisor del certificado...") y el regex original,
# sólo con "-", los perdía en silencio -- 4 claves reales nunca cargadas
# en `pedimento_identifiers` (PR #158, 2026-09-29), ninguna detectada
# porque nunca se verificó la cuenta total del documento contra un
# conteo independiente, sólo que las que SÍ se encontraban fueran
# correctas.
_IDENTIFICADOR_APENDICE_RE = re.compile(r"^([A-Z][A-Z0-9])\s*[-–]\s*(.+)$")
# "G"/"P" (General/Particular, visto en el documento real) rodeada de espacio
# simple, en cualquier posición de la línea -- no siempre al final: la
# columna "Supuestos de Aplicación" sigue en la MISMA línea física.
_NIVEL_RE = re.compile(r"\s([GP])\s")


def parse_identifiers(lines: list[str]) -> list[ParsedIdentifier]:
    """Apéndice 8: sólo `code` + `level`, igual criterio que `PedimentoClave`.

    La descripción corta de cada clave se envuelve a la línea siguiente
    mezclada con fragmentos de "Supuestos de Aplicación"/"Complemento 1-3"
    de la misma fila (layout de 6 columnas, peor que las 2 del Apéndice 2)
    -- no hay heurística de texto que las separe sin arriesgar prosa
    corrupta. `code` y `level` sí se extraen con garantía: los dos viven
    siempre en la primera línea de la entrada, antes de que empiece esa
    mezcla (174 entradas verificadas contra el documento real, sin
    duplicados de `(code, level)`).

    10 de las 174 no traen `level` -- códigos con una estructura distinta
    ("A1", "C2", "D1", "S1"... encadenan directo a "Para <clave> señalar:"
    sin pasar por G/P) -- quedan con `level=None`, lo que el documento
    trae, no un hueco de parseo.
    """
    filas: list[ParsedIdentifier] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or _NOISE_RE.search(line):
            continue
        if len(line) - len(line.lstrip()) >= 3:
            continue
        m = _IDENTIFICADOR_APENDICE_RE.match(line)
        if not m:
            continue
        nivel = _NIVEL_RE.search(m.group(2))
        filas.append(ParsedIdentifier(code=m.group(1), level=nivel.group(1) if nivel else None))
    return filas


# ── Apéndice 8: etiqueta + Supuestos de Aplicación (por coordenadas) ────────

#: Columnas reales del Apéndice 8, verificadas contra `pdftotext
#: -bbox-layout` de la página 142 del PDF real (2026-10-06): "Clave" (código
#: + etiqueta, envueltos juntos) hasta antes de "Nivel"; "Nivel" es G/P
#: suelto; "Supuestos de Aplicación" es la tercera columna. "Complemento
#: 1/2/3" siguen después y quedan fuera de este alcance (ver docstring de
#: `PedimentoIdentifier`). El límite real entre "Supuestos" y "Complemento
#: 1" está entre x=322.6 (última palabra real de Supuestos, fila de "AC")
#: y x=359.9 (primera palabra real de Complemento 1, "Número") -- 360.0
#: quedaba a 0.1pt de "Número" y se lo tragaba (regresión real: el texto
#: de Complemento 1 colándose en `supuestos_de_aplicacion` de "AC"). 350.0
#: deja margen de sobra a los dos lados.
_X_CODIGO_MAX = 115.0
_X_CLAVE_MAX = 180.0
_X_NIVEL_MIN = 180.0
_X_NIVEL_MAX = 215.0
_X_SUPUESTOS_MIN = 215.0
_X_SUPUESTOS_MAX = 350.0

# El guión (o guión largo, "–" U+2013 -- ver `_IDENTIFICADOR_APENDICE_RE`)
# a veces llega pegado al código como un solo token bbox ("AC-", "CR–") y a
# veces como palabra aparte ("AF" + "-"): el opcional cubre el primer caso,
# el segundo ya queda fuera de la columna de código por posición X.
_CODIGO_SOLO_RE = re.compile(r"^([A-Z][A-Z0-9])[-–]?$")


def _lineas_de_columna(
    palabras: list[_Palabra], x_min: float, x_max: float, y_min: float, y_max: float
) -> tuple[list[float], list[str]]:
    por_y: dict[float, list[_Palabra]] = {}
    for p in palabras:
        if x_min <= p.x < x_max and y_min < p.y < y_max:
            por_y.setdefault(p.y, []).append(p)
    ys = sorted(por_y)
    textos = [" ".join(pp.texto for pp in sorted(por_y[y], key=lambda pp: pp.x)) for y in ys]
    return ys, textos


#: Tolerancia para decidir si una línea de columna "empieza" en la misma
#: fila que un ancla (código) -- mismo criterio que `nivel_de` (0.063pt de
#: ruido real medido entre "AC-" y su "G", filas reales separadas por
#: >=25pt).
_TOLERANCIA_FILA = 1.0


def _texto_por_ancla(
    lineas_y: list[float], lineas_texto: list[str], anclas_y: list[float]
) -> list[list[str]]:
    """Reparte las líneas de UNA columna entre anclas consecutivas, por
    posición Y -- NO por programación dinámica.

    A diferencia de `ingestion.snice.tariff_headings` (LIGIE): ahí el
    código queda CENTRADO frente a la PRIMERA ORACIÓN de una descripción
    de varias líneas, verificado contra ese documento. Aquí el código
    queda ALINEADO ARRIBA con la primera línea real de cada columna --
    verificado contra la página 142 del PDF real: "AC-" y el primer
    renglón de su propio "Supuestos de Aplicación" comparten la misma Y.
    Reusar el criterio de LIGIE aquí (centrado por primera oración) hizo
    que el motor SUBCONTARA la columna de Supuestos de un ancla real
    ("AV", cuyo texto termina en "... por cada remesa") y le regalara la
    cola a la fila siguiente ("A3") -- regresión real, encontrada al
    verificar contra el documento, no una suposición. El reparto por
    intervalo de Y es correcto para ESTE documento porque el ancla real sí
    empieza su propia fila en cada columna -- no hay centrado que
    respetar.
    """
    resultado: list[list[str]] = [[] for _ in anclas_y]
    idx_ancla = -1
    for y, texto in zip(lineas_y, lineas_texto, strict=True):
        while idx_ancla + 1 < len(anclas_y) and anclas_y[idx_ancla + 1] <= y + _TOLERANCIA_FILA:
            idx_ancla += 1
        if idx_ancla >= 0:
            resultado[idx_ancla].append(texto)
    return resultado


def _identificadores_de_pagina(palabras: list[_Palabra]) -> list[ParsedIdentifier]:
    """(code, level, label, supuestos_de_aplicacion) de una página bbox del
    Apéndice 8 -- código y nivel se re-verifican aquí independientemente del
    parser de texto plano (`parse_identifiers`); si alguna vez discreparan,
    es señal de que uno de los dos tiene un error, no algo que conciliar en
    silencio.
    """
    anclas: list[tuple[float, str]] = []
    niveles: list[tuple[float, str]] = []
    for p in palabras:
        if p.x < _X_CODIGO_MAX:
            m = _CODIGO_SOLO_RE.match(p.texto)
            if m:
                anclas.append((p.y, m.group(1)))
        elif _X_NIVEL_MIN <= p.x < _X_NIVEL_MAX and p.texto in ("G", "P"):
            niveles.append((p.y, p.texto))
    anclas.sort(key=lambda a: a[0])
    if not anclas:
        return []

    def nivel_de(y_codigo: float) -> str | None:
        # "G"/"P" y su código comparten la misma fila visual pero NO
        # siempre la misma yMin exacta -- verificado contra el PDF real:
        # "AC-" en y=149.115, su "G" en y=149.178 (0.063pt de diferencia,
        # ruido de línea base de fuente, no un salto de línea real). Media
        # línea de tolerancia (6pt) no arriesga cruzar a la fila vecina,
        # que en este documento dista >=25pt.
        candidatos = [(abs(y_codigo - y), v) for y, v in niveles if abs(y_codigo - y) <= 6]
        return min(candidatos)[1] if candidatos else None

    # El encabezado de columnas ("Clave  Nivel  Supuestos de Aplicación
    # Complemento 1 Complemento 2 Complemento 3") se repite en cada página,
    # antes de la primera ancla real -- sin excluirlo, su texto se mezcla
    # con la primera entrada (regresión real: "Supuestos de Aplicación"
    # colándose en el texto de la clave "AC"). "Nivel" no aparece nunca
    # como dato real (los valores son "G"/"P"), así que sirve de marca
    # inequívoca del encabezado, página por página -- no se asume una
    # posición fija.
    y_encabezado = min((p.y for p in palabras if p.texto == "Nivel"), default=0.0)
    y_min, y_max = y_encabezado, float("inf")
    anclas_y = [a[0] for a in anclas]

    clave_y, clave_texto = _lineas_de_columna(palabras, 0.0, _X_CLAVE_MAX, y_min, y_max)
    clave_por_ancla = _texto_por_ancla(clave_y, clave_texto, anclas_y)

    supuestos_y, supuestos_texto = _lineas_de_columna(
        palabras, _X_SUPUESTOS_MIN, _X_SUPUESTOS_MAX, y_min, y_max
    )
    supuestos_por_ancla = _texto_por_ancla(supuestos_y, supuestos_texto, anclas_y)

    resultado = []
    for i, (y_code, code) in enumerate(anclas):
        lineas_clave = clave_por_ancla[i]
        # La primera línea trae el código pegado al frente del label -- se
        # quita por posición (primera palabra de esa línea), no por texto,
        # para no depender de que el código no se repita dentro del label.
        label = None
        if lineas_clave:
            primera = lineas_clave[0].split(" ", 1)
            resto_primera = primera[1] if len(primera) > 1 else ""
            crudo_label = " ".join([resto_primera, *lineas_clave[1:]]).strip()
            crudo_label = " ".join(crudo_label.split())
            # EO/PO (mismo hallazgo del guión largo que `_IDENTIFICADOR_APENDICE_RE`):
            # ahí el guión es una palabra bbox SEPARADA del código ("EO" y "–"
            # como dos tokens), no pegada como en "AC-" -- sin este strip queda
            # "– Emisor del certificado..." con el guión colgando al frente.
            crudo_label = re.sub(r"^[-–]\s*", "", crudo_label)
            label = crudo_label or None

        crudo_supuestos = " ".join(supuestos_por_ancla[i]).strip()
        texto_supuestos: str | None = " ".join(crudo_supuestos.split()) or None

        resultado.append(
            ParsedIdentifier(
                code=code,
                level=nivel_de(y_code),
                label=label,
                supuestos_de_aplicacion=texto_supuestos,
            )
        )
    return resultado


#: Desplazamiento de Y entre páginas al combinarlas en una sola secuencia
#: (ver `parse_identifiers_con_texto`). Mayor que cualquier altura de
#: página real (792pt, tamaño carta, igual que el Apéndice 1 ya documentó
#: en `ingestion.snice.tariff_headings`) -- dos páginas consecutivas quedan
#: a >=200pt en el espacio combinado, muy por encima de la tolerancia de
#: 6pt que usa `nivel_de` o la separación real entre filas (>=10pt).
_OFFSET_ENTRE_PAGINAS = 1000.0


def parse_identifiers_con_texto(
    pdf_path: str, *, first_page: int, last_page: int
) -> list[ParsedIdentifier]:
    """Apéndice 8 completo: `code` + `level` + `label` + `supuestos_de_aplicacion`,
    por coordenadas (`pdftotext -bbox-layout`) -- a diferencia de
    `parse_identifiers`, que sólo lee `code`/`level` de texto plano.

    `first_page`/`last_page` (1-based, inclusive) los calcula quien llama a
    partir de `find_appendix_headings`/`appendix_block` -- este módulo no
    sabe de líneas de `-layout`, sólo de páginas bbox.

    TODAS LAS PÁGINAS SE TRATAN COMO UNA SOLA SECUENCIA, NO PÁGINA POR
    PÁGINA -- regresión real encontrada contra el documento: sólo la
    PRIMERA página del Apéndice (142) repite el encabezado de columnas;
    las siguientes no. Sin encabezado que lo marque, el texto huérfano que
    continúa de la ÚLTIMA entrada de la página anterior se mezclaba con la
    PRIMERA entrada de la página nueva (caso real: "A3", página 145 --
    traía pegada la cola de "...presentada ante el módulo de selección
    automatizado." de la entrada anterior). Cada palabra se desplaza por
    `_OFFSET_ENTRE_PAGINAS * (página - primera)` antes de procesarlas
    juntas, así que el único encabezado real (el de la página 142) es el
    único punto de corte, y nada queda huérfano entre páginas.
    """
    todas: list[_Palabra] = []
    for indice, (_, bbox_xml) in enumerate(
        extract_bbox_pages(pdf_path, first_page=first_page, last_page=last_page)
    ):
        desplazamiento = indice * _OFFSET_ENTRE_PAGINAS
        todas.extend(_Palabra(p.x, p.y + desplazamiento, p.texto) for p in _palabras_de(bbox_xml))

    # Clave (code, level), NO sólo code: 6 claves reales repiten código con
    # nivel G Y P, cada una con su propia etiqueta y supuesto distintos
    # (p. ej. "CF- Registro..." G vs "CF- Preferencia..." P, página 147) --
    # con code solo como clave, `setdefault` se quedaba con la primera de
    # las dos y perdía la segunda en silencio (hallazgo real: CF, EP, IF,
    # SH, TB, ZL quedaban con un solo nivel de los dos que trae el PDF).
    encontrados: dict[tuple[str, str | None], ParsedIdentifier] = {}
    for parsed in _identificadores_de_pagina(todas):
        encontrados.setdefault((parsed.code, parsed.level), parsed)
    return sorted(encontrados.values(), key=lambda p: (p.code, p.level or ""))
