"""RAW -> PARSED del Anexo 22 (Instructivo para el llenado del pedimento).

Fuente: RGCE 2026, publicado en el DOF el 15-ene-2026. Este módulo cubre los
4 catálogos de referencia que Persona 1 aprobó cargar (Opción B, 2026-09-08):
aduanas/secciones, unidades de medida, claves de pedimento e identificadores
de regulaciones no arancelarias. El resto del Anexo 22 (Apéndice 8 completo,
el texto legal de cada clave de pedimento, y la correlación fracción -> NOM,
que este documento no trae) queda como deuda documentada.

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
