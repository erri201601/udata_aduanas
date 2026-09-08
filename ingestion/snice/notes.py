"""PARSED de las notas de Sección y de Capítulo de la LIGIE.

Son lo que distingue 8471 de 8528 para una computadora portátil: sin ellas,
RGI 1 devuelve ambas partidas como candidatas, RGI 3 a) no discrimina entre
descripciones igual de específicas, y el motor cae a RGI 3 c) —la partida
más alta por orden numérico— que elige la partida equivocada. La regla se
aplica bien; lo que falta es la nota que excluye (Persona 1, 2026-09-08).

ESTRUCTURA REAL DEL DOCUMENTO

Cada Capítulo/Sección trae un encabezado centrado ("Capítulo 84.", "Sección
XVI.") seguido, cuando aplica, de un bloque "Notas." con numerales (1., 2.…)
y sub-incisos (a), A), 1°)…) hasta que empieza la tabla de partidas — no
todas las secciones o capítulos tienen notas, y eso no es un hueco de
parseo. La tabla se reconoce por su propia estructura: una fila de partida/
subpartida/fracción empieza en columna 0 con un código numérico
("84.01", "8401.10", "8401.10.01"); el texto de las notas, en cambio, va
siempre sangrado. Esa sangría es la única señal que hace falta para saber
dónde termina el bloque de notas — mismo principio que separó columnas por
sangría en el Apéndice 9 del Anexo 22.

No se granula por numeral: cada bloque de notas de un Capítulo/Sección es
UNA fila de `LegalRule`, porque `excludes()` en
`database/repositories/notes.py` ya busca por texto (`ilike`) dentro de la
nota completa — no hace falta citar "Nota 2, inciso a)" para que RGI 1
pueda excluir una partida por ella.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


def extract_text(pdf_path: str) -> list[str]:
    """`pdftotext -layout` sobre el PDF de la LIGIE ya descargado."""
    resultado = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True,
        check=True,
        text=True,
    )
    return resultado.stdout.splitlines(keepends=True)

_CAPITULO_RE = re.compile(r"^\s*Cap[ií]tulo\s+(\d{1,2})\.\s*$")
_SECCION_RE = re.compile(r"^\s*Secci[oó]n\s+([IVXLC]+)\.\s*$")
_NOTAS_RE = re.compile(r"^\s*Notas?\.\s*$")
#: Fila de partida/subpartida/fracción: código numérico en columna 0. Marca
#: el fin del bloque de notas — la prosa de las notas siempre va sangrada.
_TABLA_RE = re.compile(r"^\d{2}(?:\.\d{2}){1,2}")
_NOISE_RE = re.compile(
    r"Calle Pachuca|Direcci[oó]n General de Facilitaci[oó]n|Comercial y de Comercio Exterior|^\s*\d+\s*$"
)


@dataclass(frozen=True)
class ParsedNote:
    path: str  # "Capítulo 84" o "Sección XVI"
    rule_number: str  # "NOTAS-CAP-84" o "NOTAS-SEC-XVI"
    text: str


def _encabezados(lines: list[str]) -> list[tuple[int, str, str]]:
    """(índice, path, rule_number) de cada Capítulo/Sección, en orden de aparición.

    Sólo la PRIMERA aparición de cada número/numeral cuenta como encabezado
    real: varios capítulos y secciones se repiten en el documento (índices,
    referencias cruzadas) y sólo la primera es el encabezado que abre su
    propio bloque de notas y tabla.
    """
    vistos: set[str] = set()
    encabezados: list[tuple[int, str, str]] = []
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        m = _CAPITULO_RE.match(line)
        if m:
            clave = f"CAP-{m.group(1)}"
            if clave not in vistos:
                vistos.add(clave)
                encabezados.append((i, f"Capítulo {m.group(1)}", f"NOTAS-CAP-{m.group(1)}"))
            continue
        m = _SECCION_RE.match(line)
        if m:
            clave = f"SEC-{m.group(1)}"
            if clave not in vistos:
                vistos.add(clave)
                encabezados.append((i, f"Sección {m.group(1)}", f"NOTAS-SEC-{m.group(1)}"))
    encabezados.sort(key=lambda t: t[0])
    return encabezados


def parse_notes(lines: list[str]) -> list[ParsedNote]:
    """Un `ParsedNote` por cada Capítulo/Sección que trae un bloque "Notas.".

    No todos lo traen — un capítulo sin notas simplemente no aparece en el
    resultado, en vez de generar una fila vacía.
    """
    encabezados = _encabezados(lines)
    resultado: list[ParsedNote] = []

    for idx, (inicio, path, rule_number) in enumerate(encabezados):
        fin_bloque = encabezados[idx + 1][0] if idx + 1 < len(encabezados) else len(lines)

        # Busca "Notas." entre este encabezado y el siguiente.
        inicio_notas = None
        for i in range(inicio + 1, fin_bloque):
            if _NOTAS_RE.match(lines[i].rstrip("\n")):
                inicio_notas = i + 1
                break
        if inicio_notas is None:
            continue  # este Capítulo/Sección no trae notas

        partes: list[str] = []
        for i in range(inicio_notas, fin_bloque):
            line = lines[i].rstrip("\n")
            if _TABLA_RE.match(line):
                break  # empezó la tabla de partidas: las notas terminaron aquí
            if not line.strip() or _NOISE_RE.search(line):
                continue
            partes.append(line.strip())

        texto = " ".join(partes)
        if texto:
            resultado.append(ParsedNote(path=path, rule_number=rule_number, text=texto))

    return resultado
