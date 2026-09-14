"""RAW -> PARSED de las RGCE 2026 (Resolución General de Comercio Exterior, DOF).

Fuente: nota del DOF, HTML completo (no PDF):
`https://dof.gob.mx/nota_detalle_popup.php?codigo=5777199`. Reconocimiento
completo en `docs/RECONOCIMIENTO_RGCE_2026.md` (RAW ya en MinIO,
content_hash `272346ff5e9f18eb267348a9d54813c80b9b4d162107306b0e55aaa4ac37eaaa`).

Alcance de esta primera carga (decisión de Persona 1, 2026-09-14): sólo el
cuerpo de las 550 reglas, numeración decimal Título.Capítulo.Regla (p. ej.
"1.1.1."). Fuera los 30 Anexos —el Anexo 6 se carga en un PR propio,
después, por ser la compilación de criterios de clasificación que el art. 48
de la Ley Aduanera obliga a publicar— y fuera los Transitorios: se corta el
texto en el primer "Transitorios", igual criterio que con la Ley Aduanera
(`ingestion.diputados.ley_aduanera`). El Anexo 13 (tabla de multas) viene
DESPUÉS de los Transitorios en este documento, así que el mismo corte lo
excluye sin lógica aparte.

Por qué este parser no reutiliza el de la Ley Aduanera ni `rag.chunking`: la
RGCE no trae notas de reforma inline ("(Reformado DOF ...)") junto a cada
regla —es una resolución anual completa, reemplazada entera cada año—, y su
numeración es decimal, no "ARTICULO N". La vigencia por regla sale de un
cruce con los Transitorios, no de una nota pegada al texto.

VIGENCIA — de los Transitorios, nunca inventada:

- Transitorio Primero: vigor uniforme del documento (2026-01-01 a
  2026-12-31). Es el respaldo de toda regla que ningún otro Transitorio
  mencione.
- Transitorio Tercero: dos reglas (2.1.1. y 4.6.1.) entran después
  (2026-02-02), con su propia fecha, textual en el Transitorio.
- Transitorio Cuarto: 13 reglas entran en términos del transitorio de OTRO
  decreto (la reforma a la Ley Aduanera, DOF 19-11-2025) que no es una
  fuente almacenada con `content_hash` en este repo. Ponerles cualquier
  fecha sería inventar vigencia —el mismo bug que ya se cazó en la Ley
  Aduanera (hallazgo de Persona 3, 2026-09-08)—, así que se marcan
  `needs_validation=True` con su motivo y NO se les asigna
  `valid_from`/`valid_to`. El cargador (siguiente PR) las excluye de la
  carga y las reporta.

Sin dependencias nuevas (no hay `bs4` ni `lxml` en el proyecto): el HTML de
esta nota es una exportación de Word, miles de `<span>` de una sola corrida
de texto. `html.parser.HTMLParser` de la librería estándar basta: tratar los
tags de bloque (div/tr/br/p) como salto de línea y reconocer negritas —la
única marca que el propio documento usa para distinguir el número de regla
del cuerpo, a diferencia del "ARTICULO" en mayúsculas de la Ley Aduanera.

Dos regresiones reales encontradas al validar contra el HTML real (no contra
prosa inventada):

1. Sin filtrar por longitud del primer componente, el parser confundía
   códigos de fracción arancelaria citados en negritas dentro de alguna
   regla (p. ej. "9901.00.11.") con encabezados de regla, porque calzan el
   mismo patrón N.N.N. — los 7 Títulos reales nunca pasan de un dígito, así
   que el primer componente se exige de un solo dígito.
2. La nota del DOF trae un SEGUNDO bloque "Primero./Segundo./Tercero." más
   adelante en el mismo HTML, de OTRO instrumento —no de las RGCE—, antes de
   llegar al Anexo 13. `parse_transitorios` se queda con la PRIMERA
   aparición de cada ordinal: si se sobreescribiera con la última, el
   Transitorio Primero real (el que fija la vigencia de las 550 reglas)
   quedaría reemplazado por el de ese otro instrumento.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

_MESES = {
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

_BLOCK_TAGS = frozenset({"div", "tr", "br", "p", "h1", "h2", "li", "table"})
_SKIP_TAGS = frozenset({"script", "style", "title", "head"})
# Caracteres de uso privado Unicode, nunca presentes en el DOF: marcan el
# inicio/fin de una corrida en negritas para poder reconocerla después de
# aplanar el HTML a líneas de texto.
_BOLD_OPEN = ""
_BOLD_CLOSE = ""


def _strip_markers(text: str) -> str:
    return text.replace(_BOLD_OPEN, "").replace(_BOLD_CLOSE, "")


class _LineExtractor(HTMLParser):
    """HTML -> líneas de texto, una por bloque (div/tr/br/p), marcando negritas.

    No intenta ser un extractor de HTML general: basta con lo que este
    documento necesita (ver docstring del módulo). Cada `<span>` en negritas
    (`font-weight:bold` en su `style`) queda envuelto en `_BOLD_OPEN`/
    `_BOLD_CLOSE`; el resto del parser usa esa marca para reconocer
    encabezados de regla y de Transitorio.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buf: list[str] = []
        self._skip_depth = 0
        self._span_stack: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag == "span":
            style = (dict(attrs).get("style") or "").replace(" ", "")
            is_bold = "font-weight:bold" in style
            self._span_stack.append(is_bold)
            if is_bold:
                self._buf.append(_BOLD_OPEN)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "span" and self._span_stack and self._span_stack.pop():
            self._buf.append(_BOLD_CLOSE)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._buf.append(data)

    def _flush(self) -> None:
        line = "".join(self._buf).replace("\xa0", " ")
        self._buf = []
        if _strip_markers(line).strip():
            self.lines.append(line)

    def close(self) -> None:
        super().close()
        self._flush()


def extract_lines(html: str) -> list[str]:
    """Aplana el HTML de la nota a una línea de texto por bloque (div/tr/br/p).

    Análogo a `pdftotext -layout` para el caso PDF de la Ley Aduanera: ambos
    devuelven `list[str]` para que el resto del parser trabaje línea a línea.
    """
    parser = _LineExtractor()
    parser.feed(html)
    parser.close()
    return parser.lines


_HEADING_RE = re.compile(rf"^\s*{_BOLD_OPEN}(\d\.\d+\.\d+\.)")
_TRANSITORIOS_RE = re.compile(r"^\s*Transitorios\s*$")
_TRANSITORIO_HEADING_RE = re.compile(
    rf"^\s*{_BOLD_OPEN}(Primero|Segundo|Tercero|Cuarto|Quinto|Sexto|"
    rf"S[ée]ptimo|Octavo|Noveno|D[ée]cimo)\."
)
_REGLA_CITADA_RE = re.compile(r"\d\.\d+\.\d+\.")
_FECHA_GRUPO = r"(\d{1,2})o?\.?\s+de\s+(" + "|".join(_MESES) + r")\s+de\s+(\d{4})"
_VIGOR_DESDE_RE = re.compile(r"entrar[áa]n?\s+en\s+vigor\s+el\s+" + _FECHA_GRUPO, re.IGNORECASE)
_VIGENTE_HASTA_RE = re.compile(r"vigente\s+hasta\s+el\s+" + _FECHA_GRUPO, re.IGNORECASE)


def _fecha_de(patron: re.Pattern[str], texto: str) -> date | None:
    m = patron.search(texto)
    if not m:
        return None
    dia, mes, anio = m.groups()
    return date(int(anio), _MESES[mes.lower()], int(dia))


def parse_rule_bodies(lines: list[str]) -> list[tuple[str, str]]:
    """(rule_number, text) de cada regla del cuerpo, cortando antes de "Transitorios".

    `rule_number` sin el punto final ("1.1.1", no "1.1.1."). Sólo reconoce
    encabezados EN NEGRITAS con el primer componente de un solo dígito: es lo
    que distingue el número de regla real de un código de fracción
    arancelaria citado en negritas dentro del cuerpo (ver docstring del
    módulo).
    """
    fin = next(
        (
            i
            for i, linea in enumerate(lines)
            if _TRANSITORIOS_RE.match(_strip_markers(linea).strip())
        ),
        len(lines),
    )
    cuerpo = lines[:fin]

    reglas: list[tuple[str, str]] = []
    numero: str | None = None
    texto: list[str] = []

    def flush() -> None:
        if numero is not None:
            unido = " ".join(_strip_markers(t) for t in texto)
            reglas.append((numero, " ".join(unido.split())))

    for raw in cuerpo:
        m = _HEADING_RE.match(raw)
        if m:
            flush()
            numero = m.group(1).rstrip(".")
            texto = [raw[m.end() :]]
            continue
        if numero is not None:
            texto.append(raw)
    flush()
    return reglas


def parse_transitorios(lines: list[str]) -> dict[str, str]:
    """{ordinal en mayúsculas: texto} de cada Transitorio, tras "Transitorios".

    Sólo la PRIMERA aparición de cada ordinal (ver docstring del módulo): el
    documento trae un segundo bloque "Primero./Segundo./Tercero." más
    adelante en la misma nota del DOF, de OTRO instrumento — no de las RGCE.
    """
    inicio = next(
        (
            i
            for i, linea in enumerate(lines)
            if _TRANSITORIOS_RE.match(_strip_markers(linea).strip())
        ),
        None,
    )
    if inicio is None:
        return {}
    resto = lines[inicio + 1 :]

    transitorios: dict[str, str] = {}
    ordinal: str | None = None
    texto: list[str] = []

    def flush() -> None:
        if ordinal is not None:
            transitorios.setdefault(ordinal, " ".join(_strip_markers(t) for t in texto))

    for raw in resto:
        m = _TRANSITORIO_HEADING_RE.match(raw)
        if m:
            flush()
            ordinal = m.group(1).upper()
            texto = [raw[m.end() :]]
            continue
        if ordinal is not None:
            texto.append(raw)
    flush()
    return transitorios


def reglas_citadas(texto: str) -> list[str]:
    """Números de regla (patrón N.N.N.) citados dentro de un Transitorio."""
    return [n.rstrip(".") for n in _REGLA_CITADA_RE.findall(texto)]


@dataclass(frozen=True)
class ParsedRule:
    rule_number: str
    text: str
    # None sólo cuando `needs_validation` es True: no hay fuente almacenada
    # con content_hash para esa fecha (Transitorio Cuarto). Nunca se rellena
    # con una fecha adivinada.
    valid_from: date | None
    valid_to: date | None
    needs_validation: bool = False
    needs_validation_reason: str | None = None


TRANSITORIO_CUARTO_MOTIVO = (
    "Transitorio Cuarto de las RGCE 2026: entra en vigor en términos del "
    "transitorio del Decreto que reforma la Ley Aduanera (DOF 19-11-2025). "
    "Esa fecha no viene de una fuente almacenada con content_hash en este "
    "repo -- ponerle 2026-01-01 o cualquier otra sería inventar vigencia."
)


def parse_rules(html: str) -> list[ParsedRule]:
    """RAW (HTML ya descargado) -> `ParsedRule` por regla, con vigencia resuelta.

    No hace red ni toca MinIO ni la base: recibe el HTML ya capturado (regla
    7 CLAUDE.md, RAW primero) y sólo parsea. Falla ruidoso (`ValueError`) si
    encuentra números de regla duplicados o si no puede extraer la vigencia
    del documento — un extractor que "se las arregla" produce datos
    incorrectos en silencio.
    """
    lines = extract_lines(html)
    cuerpos = parse_rule_bodies(lines)

    numeros = [n for n, _ in cuerpos]
    duplicados = {n for n in numeros if numeros.count(n) > 1}
    if duplicados:
        raise ValueError(f"números de regla duplicados en el documento: {sorted(duplicados)}")

    transitorios = parse_transitorios(lines)

    primero = transitorios.get("PRIMERO", "")
    valid_from_doc = _fecha_de(_VIGOR_DESDE_RE, primero)
    valid_to_doc = _fecha_de(_VIGENTE_HASTA_RE, primero)
    if valid_from_doc is None or valid_to_doc is None:
        raise ValueError("no se pudo extraer la vigencia del documento del Transitorio Primero")

    tercero = transitorios.get("TERCERO", "")
    reglas_tercero = set(reglas_citadas(tercero))
    fecha_tercero = _fecha_de(_VIGOR_DESDE_RE, tercero)
    if reglas_tercero and fecha_tercero is None:
        raise ValueError("el Transitorio Tercero cita reglas pero no se pudo extraer su fecha")

    reglas_cuarto = set(reglas_citadas(transitorios.get("CUARTO", "")))

    parsed: list[ParsedRule] = []
    for numero, texto in cuerpos:
        if numero in reglas_cuarto:
            parsed.append(
                ParsedRule(
                    rule_number=numero,
                    text=texto,
                    valid_from=None,
                    valid_to=None,
                    needs_validation=True,
                    needs_validation_reason=TRANSITORIO_CUARTO_MOTIVO,
                )
            )
        elif numero in reglas_tercero:
            parsed.append(
                ParsedRule(
                    rule_number=numero,
                    text=texto,
                    valid_from=fecha_tercero,
                    valid_to=valid_to_doc,
                )
            )
        else:
            parsed.append(
                ParsedRule(
                    rule_number=numero,
                    text=texto,
                    valid_from=valid_from_doc,
                    valid_to=valid_to_doc,
                )
            )
    return parsed
