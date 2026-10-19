"""RAW -> PARSED del sumario diario del DOF (§11 DOF, §43 Sprint 6).

`https://dof.gob.mx/sumario.xml` -- RSS 2.0 real, verificado a mano el
13-oct-2026 (17 `<item>`, uno de ellos literalmente un "Decreto por el que
se modifica la Tarifa de la Ley de los Impuestos Generales de Importación
y de Exportación", `codigo=5800977`). Sin parámetro de fecha: el feed
siempre refleja la edición MÁS RECIENTE -- no hay forma de pedir un día
anterior por este endpoint. El vigilante sólo puede ver "hoy", corriendo
una vez por día; programarlo (cron/scheduler) es infraestructura aparte,
no esta tarea.

Este módulo sólo parsea -- no decide relevancia ni escribe nada. Eso es
`es_relevante_comercio_exterior`/`clasificar_event_kind` (abajo, puras,
sin sesión de base) y `ingestion.dof.load.load_regulatory_events`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from xml.etree import ElementTree as ET

SUMARIO_URL = "https://dof.gob.mx/sumario.xml"

_CODIGO_RE = re.compile(r"codigo=(\d+)")


@dataclass(frozen=True)
class ParsedSumarioItem:
    authority: str
    description: str
    source_url: str
    value_date: date
    #: `None` si el link no trae el parámetro `codigo` -- no debería pasar
    #: con el formato real del feed, pero no se asume.
    codigo: str | None


def _codigo_de(url: str) -> str | None:
    m = _CODIGO_RE.search(url)
    return m.group(1) if m else None


def parse_sumario(xml_bytes: bytes) -> list[ParsedSumarioItem]:
    """Cada `<item>` del feed -> `ParsedSumarioItem`.

    `ISO-8859-1` es la codificación real que declara el XML (verificado:
    decodificar como UTF-8 rompería los acentos). Falla ruidoso si un
    `<item>` no trae `valueDate` en el formato esperado -- no se le
    inventa una fecha (regla 7 CLAUDE.md).
    """
    root = ET.fromstring(xml_bytes.decode("iso-8859-1"))
    items: list[ParsedSumarioItem] = []
    for item in root.findall(".//item"):
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        descripcion = unescape((item.findtext("description") or "").strip())
        fecha_raw = (item.findtext("valueDate") or "").strip()
        items.append(
            ParsedSumarioItem(
                authority=titulo,
                description=descripcion,
                source_url=link,
                value_date=datetime.strptime(fecha_raw, "%d/%m/%Y").date(),
                codigo=_codigo_de(link),
            )
        )
    return items


#: Verificado contra las 17 entradas reales del 13-oct-2026: ninguna de
#: comercio exterior se pierde con este conjunto, y ninguna de las 15
#: irrelevantes (Salud, Mujeres, ISSSTE, INE, FGR...) entra por error.
#: `tipo de cambio`/`tasas de interés` de Banxico se EXCLUYEN a
#: propósito: ya tienen su propio pipeline (`ingestion/banxico/`), más
#: preciso que una palabra clave -- duplicarlo aquí confundiría cuál es
#: la fuente de verdad para el FIX.
_PALABRAS_COMERCIO_EXTERIOR = (
    "arancel",
    "impuestos generales de importación",
    "impuestos generales de exportación",
    "comercio exterior",
    "aduana",
    "tigie",
    "fracción arancelaria",
    "secretaría de economía",
    "cuota compensatoria",
    "norma oficial mexicana",
    "prosec",
    "tránsito internacional de mercancías",
)

_PALABRAS_EXCLUIDAS = (
    "tipo de cambio",
    "tasa de interés",
    "tasas de interés",
)


def es_relevante_comercio_exterior(item: ParsedSumarioItem) -> bool:
    """`True` si el título o la descripción mencionan algo de comercio
    exterior/aduanas -- el filtro que evita que las ~15 de cada ~17
    entradas sin relación (Salud, INE, ISSSTE...) lleguen a
    `regulatory_events` como ruido."""
    texto = f"{item.authority} {item.description}".lower()
    if any(palabra in texto for palabra in _PALABRAS_EXCLUIDAS):
        return False
    return any(palabra in texto for palabra in _PALABRAS_COMERCIO_EXTERIOR)


def clasificar_event_kind(item: ParsedSumarioItem) -> str:
    """`REGULATORY_EVENT_KIND` a partir del verbo del título -- heurística
    simple y conservadora: ante la duda, `PUBLICATION` (no se afirma una
    reforma o una abrogación que el texto no dice con claridad)."""
    texto = item.description.lower()
    if "fe de erratas" in texto or "erratum" in texto:
        return "ERRATA"
    if "abroga" in texto or "deroga" in texto:
        return "REPEAL"
    if "modifica" in texto or "reforma" in texto or "adiciona" in texto:
        return "AMENDMENT"
    return "PUBLICATION"
