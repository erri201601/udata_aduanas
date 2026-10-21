"""Qué toca una publicación del DOF: fracciones, NOM y entrada en vigor (ADR 0022).

El vigilante (`watcher_cli`) captura del sumario el título y el enlace de cada
publicación de comercio exterior. Este módulo lee la nota misma y extrae tres
cosas que Sentinel necesita para decir a quién afecta:

- **Fracciones citadas**, de las tablas de la nota (`tablas_html`) y del
  texto. Son las que la publicación nombra; no se deduce ninguna.
- **NOM, sólo las del título.** El cuerpo trae menciones de paso: el Código de
  Conducta de la SE (DOF 19-oct-2026) cita la NOM-046-SSA2 sin que tenga nada
  que ver con comercio exterior. El título dice de qué trata la publicación.
- **Entrada en vigor**, del transitorio, cuando la fórmula es inequívoca:
  «al día siguiente de su publicación», «el día de su publicación» o una fecha
  escrita. Si no la hay (un aviso de consulta pública no entra en vigor), se
  queda vacía: no se adivina.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from ingestion.se.tablas_html import cuadricula, tablas

_FRACCION: Final = re.compile(r"(?<![\d.])(\d{4})\.(\d{2})\.(\d{2})(?![\d.])")
_NOM: Final = re.compile(r"NOM-[\w./-]*\d{4}")
_MESES: Final = {
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
#: «TRANSITORIOS», «Transitorios», «TRANSITORIO ÚNICO»: la nota del 29-dic-2025
#: lo escribe en minúsculas.
_TRANSITORIO: Final = re.compile(r"TRANSITORIOS?\b(.{0,700})", re.S | re.I)
_SIGUIENTE: Final = re.compile(r"entra(?:rá)? en vigor (?:a partir del|al) día siguiente", re.I)
_MISMO_DIA: Final = re.compile(
    r"entra(?:rá)? en vigor (?:a partir de)?\s*el día de su publicación", re.I
)
#: «el 1 de enero de 2026», «el primero de enero de 2026», «el 1o. de enero…».
_FECHA: Final = re.compile(
    r"entra(?:rá)? en vigor (?:a partir )?(?:del|el) (\d{1,2}|primero)(?:o\.|º)? de (\w+) de (\d{4})",
    re.I,
)
_VIGENCIA_ANIOS: Final = re.compile(
    r"vigencia de (uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|\d+) años?", re.I
)
_NUMEROS: Final = {
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}


@dataclass(frozen=True)
class Afectacion:
    fracciones: tuple[str, ...]
    noms: tuple[str, ...]
    entra_en_vigor: date | None
    vigencia_hasta: date | None


def _texto(html: str) -> str:
    sin_scripts = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", sin_scripts)))


def _cuerpo(texto: str) -> str:
    """La nota sin la columna lateral del DOF (tipo de cambio, encuestas…)."""
    fin = texto.find("En el documento que usted está visualizando")
    return texto[:fin] if fin > 0 else texto


def fracciones_de(html: str) -> tuple[str, ...]:
    """Las fracciones que la nota cita, en tablas o en el texto, sin repetir."""
    vistas: dict[str, None] = {}
    for tabla in tablas(html):
        for fila in cuadricula(tabla.filas):
            for celda in fila[:1]:
                m = _FRACCION.fullmatch(celda.strip())
                if m:
                    vistas["".join(m.groups())] = None
    for m in _FRACCION.finditer(_cuerpo(_texto(html))):
        vistas["".join(m.groups())] = None
    return tuple(vistas)


def noms_del_titulo(titulo: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_NOM.findall(titulo)))


def _anios(valor: str) -> int | None:
    return _NUMEROS.get(valor.lower()) if not valor.isdigit() else int(valor)


def vigencia_de(html: str, publicada: date) -> tuple[date | None, date | None]:
    """`(entra_en_vigor, vigente_hasta)` del transitorio, o `None` si no es
    inequívoco. «Vigencia de N años contados a partir de su entrada en vigor»
    da el fin: el día antes del aniversario."""
    m = _TRANSITORIO.search(_cuerpo(_texto(html)))
    if not m:
        return None, None
    transitorio = m.group(1)
    entra: date | None = None
    if _SIGUIENTE.search(transitorio):
        entra = publicada + timedelta(days=1)
    elif _MISMO_DIA.search(transitorio):
        entra = publicada
    else:
        f = _FECHA.search(transitorio)
        mes = _MESES.get(f.group(2).lower()) if f else None
        if f and mes:
            dia = 1 if f.group(1).lower() == "primero" else int(f.group(1))
            entra = date(int(f.group(3)), mes, dia)
    hasta: date | None = None
    v = _VIGENCIA_ANIOS.search(transitorio)
    anios = _anios(v.group(1)) if v else None
    if entra and anios:
        try:
            hasta = entra.replace(year=entra.year + anios) - timedelta(days=1)
        except ValueError:  # 29 de febrero
            hasta = entra.replace(year=entra.year + anios, day=28) - timedelta(days=1)
    return entra, hasta


def leer(html: str, *, titulo: str, publicada: date) -> Afectacion:
    entra, hasta = vigencia_de(html, publicada)
    return Afectacion(
        fracciones=fracciones_de(html),
        noms=noms_del_titulo(titulo),
        entra_en_vigor=entra,
        vigencia_hasta=hasta,
    )
