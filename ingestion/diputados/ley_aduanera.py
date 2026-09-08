"""RAW -> PARSED de la Ley Aduanera (texto vigente, Cámara de Diputados).

Fuente: el PDF consolidado que publica la Cámara de Diputados
(`LeyesBiblio/pdf/LAdua.pdf`), complementario al DOF igual que SNICE para la
LIGIE (decisión de Persona 1, 2026-09-05): Diputados es cómodo de leer, pero
el instrumento jurídico son las reformas publicadas en el DOF. La página
`LeyesBiblio/ref/ladua.htm` confirma la última reforma vigente (19-nov-2025).

Alcance de esta primera carga: los artículos numerados del cuerpo de la ley
(1o. a 203, con sus fracciones "-A"/"-B"… insertadas). NO incluye:
- Los "Transitorios" de cada decreto de reforma (al final del documento,
  material histórico, no texto vigente citable).
- La jerarquía completa Título/Capítulo/Sección como `path`: el documento
  envuelve "Sección Primera"/"Segunda" en dos líneas de forma inconsistente
  y no se verificó una extracción confiable — `path` queda NULL, deuda
  documentada (igual criterio que las notas de capítulo de la LIGIE).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import date


def extract_text(pdf_path: str) -> list[str]:
    """`pdftotext -layout` sobre el PDF ya descargado."""
    resultado = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        capture_output=True,
        check=True,
        text=True,
    )
    return resultado.stdout.splitlines(keepends=True)


@dataclass(frozen=True)
class ParsedArticle:
    rule_number: str
    text: str
    # Fecha de derogación si el artículo fue derogado (extraída de la nota
    # "Artículo derogado DOF dd-mm-aaaa"), None si sigue vigente.
    valid_to: date | None
    # Casi nunca None (ver `_vigencia_de_notas`): sólo cuando el artículo no
    # trae ninguna nota de reforma/adición/derogación, de ningún nivel —no se
    # ha tocado desde que se promulgó la ley—. El llamador decide el respaldo
    # (la fecha de publicación original de la Ley, no la de su última reforma:
    # esa es del documento completo, no de este artículo en particular).
    valid_from_override: date | None


_HEADING_RE = re.compile(
    r"^\s*ARTICULO\s+(\d+)"
    r"(?:"
    r"\s+(bis)(?:\s+(\d+))?\.-?|"  # "49 bis." / "137 bis 1.-"
    r"o\.(?:-([A-Z])\.)?|"  # "2o." / "9o.-A."
    r"(?:-([A-Z]))?\."  # "167." / "167-G."
    r")\s*(.*)$"
)
_FOOTNOTE_RE = re.compile(
    r"^\s*(Apartado|Art[ií]culo|Cap[ií]tulo|Fracci[oó]n|Inciso|P[aá]rrafo|Secci[oó]n|T[ií]tulo)"
    r"\s+(reformad[ao]s?|adicionad[ao]s?|derogad[ao]s?)\s+DOF",
)
_ARTICULO_NOTA_RE = re.compile(r"^\s*Art[ií]culo\b", re.IGNORECASE)
# La fecha de derogación puede ser la única acción ("Artículo derogado DOF...")
# o venir después de otra en la misma nota ("...adicionado DOF ... Derogado
# DOF ...", caso real: artículo 137 bis 8) — se busca en toda la línea, no
# sólo al inicio, siempre que la nota sea de "Artículo" y no de una fracción/
# párrafo/inciso suyo.
_DEROGADO_FECHA_RE = re.compile(r"[Dd]erogad[ao]\s+DOF\s+(\d{1,2})-(\d{1,2})-(\d{4})")
_FECHA_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")
_PAGE_NOISE_RE = re.compile(
    r"^\s*\d+\s+de\s+220\s*$|LEY ADUANERA|C[ÁA]MARA DE DIPUTADOS|"
    r"Secretar[ií]a General|Secretar[ií]a de Servicios Parlamentarios|"
    r"[ÚU]ltima [Rr]eforma DOF",
)
_TRANSITORIOS_RE = re.compile(r"^\s*Transitorios\s*$")


def _fechas_en(line: str) -> list[date]:
    return [date(int(a), int(m), int(d)) for d, m, a in _FECHA_RE.findall(line)]


def _vigencia_de_notas(footnote_lines: list[str]) -> tuple[date | None, date | None]:
    """(`valid_from_override`, `valid_to`) a partir de las notas del artículo.

    `valid_to` sólo si el ARTÍCULO COMPLETO fue derogado: "Fracción derogada"/
    "Párrafo derogado"/etc. no cierran la vigencia del artículo, sólo quitan
    una parte y el resto sigue vigente (caso real: artículo 20, con una
    fracción derogada en 2013 y texto vigente después). Sólo se mira esto en
    notas que empiezan con "Artículo": es el único nivel que cierra la fila
    entera.

    `valid_from_override` tiene DOS reglas distintas según el caso:

    - DEROGADO: la fecha más antigua entre las notas de "Artículo" (adición/
      reforma/derogación) de esa fila — nunca la fecha uniforme del
      documento, que podría ser posterior a la propia derogación e invertir
      el intervalo (regresión real: artículo 38).

    - VIGENTE (la inmensa mayoría): la fecha MÁS RECIENTE entre TODAS las
      notas del artículo, sin importar su nivel. La mayoría de las reformas
      reales tocan un párrafo o un inciso, no "el artículo" completo — el
      36-A real nunca trae una nota que empiece con "Artículo", sólo
      "Párrafo reformado…"/"Inciso reformado…" — y lo que se guarda aquí es
      UNA sola fila con el artículo entero. Esa fila sólo puede afirmarse
      vigente desde la reforma más reciente que tocó CUALQUIERA de sus
      partes, nunca desde la primera vez que se tocó: usar una fecha más
      antigua citaría como vigente en una fecha histórica un texto que en
      ese momento tenía otra redacción en alguna de sus partes (regla 5
      CLAUDE.md, el mismo motivo por el que tampoco sirve la fecha del
      documento completo).

    `None` sólo cuando el artículo no trae ninguna nota, de ningún nivel: no
    se ha tocado desde que se promulgó la ley. El llamador decide el
    respaldo — la fecha de publicación original.
    """
    fechas_articulo: list[date] = []
    fechas_todas: list[date] = []
    valid_to: date | None = None
    for line in footnote_lines:
        fechas_todas.extend(_fechas_en(line))
        if not _ARTICULO_NOTA_RE.match(line):
            continue
        fechas_articulo.extend(_fechas_en(line))
        m = _DEROGADO_FECHA_RE.search(line)
        if m:
            dia, mes, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
            valid_to = date(anio, mes, dia)
    if valid_to is not None:
        return min(fechas_articulo), valid_to
    if fechas_todas:
        return max(fechas_todas), None
    return None, None


def parse_articles(lines: list[str]) -> list[ParsedArticle]:
    """Un `ParsedArticle` por cada `ARTICULO N[-LETRA]` del cuerpo de la ley.

    Se corta en el primer "Transitorios": lo que sigue es el historial de
    disposiciones transitorias de cada decreto de reforma, no el texto vigente
    de un artículo citable.
    """
    fin = next(
        (i for i, linea in enumerate(lines) if _TRANSITORIOS_RE.match(linea.rstrip("\n"))),
        len(lines),
    )
    cuerpo = lines[:fin]

    articulos: list[ParsedArticle] = []
    numero: str | None = None
    cuerpo_texto: list[str] = []
    notas: list[str] = []

    def flush() -> None:
        if numero is not None:
            texto = " ".join(t.strip() for t in cuerpo_texto if t.strip())
            valid_from_override, valid_to = _vigencia_de_notas(notas)
            articulos.append(
                ParsedArticle(
                    rule_number=numero,
                    text=texto,
                    valid_to=valid_to,
                    valid_from_override=valid_from_override,
                )
            )

    for raw in cuerpo:
        line = raw.rstrip("\n")
        if not line.strip() or _PAGE_NOISE_RE.search(line):
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush()
            base, es_bis, bis_n, ordinal_letra, letra = m.groups()[:5]
            if es_bis:
                numero = f"{base}-BIS-{bis_n}" if bis_n else f"{base}-BIS"
            else:
                letra_sufijo = ordinal_letra or letra
                numero = f"{base}-{letra_sufijo}" if letra_sufijo else base
            cuerpo_texto = [m.group(6)]
            notas = []
            continue
        if _FOOTNOTE_RE.match(line):
            notas.append(line)
            continue
        if numero is not None:
            cuerpo_texto.append(line)
    flush()
    return articulos
