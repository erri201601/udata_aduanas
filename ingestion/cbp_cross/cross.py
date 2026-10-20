"""CBP CROSS: resoluciones de clasificación de EE. UU. como casos comparables (ADR 0019).

LA FUENTE

`https://rulings.cbp.gov` tiene una API JSON pública:

- `/api/search?term=…&collection=ALL&pageSize=100&page=N&sortBy=RELEVANCE`
  busca por palabra en el texto. «7615» (la partida) encuentra resultados;
  «7615.10» no, porque los puntos parten el término.
- `/api/ruling/{número}` devuelve la resolución entera: texto, fecha, asunto,
  códigos HTSUS, y qué la revoca o la modifica.

Las resoluciones son obra del gobierno de EE. UU. (dominio público): `PUBLIC`.

QUÉ SE GUARDA Y QUÉ NO

- Los códigos HTSUS, tal como los escribe CBP. No se convierten a TIGIE
  (maestro §11).
- La subpartida HS6 de cada código, que es lo único comparable con México.
  Los capítulos 98 y 99 son disposiciones nacionales de EE. UU. (aranceles
  adicionales, regímenes especiales) y no son Sistema Armonizado: no dan HS6.
- La URL pública de la resolución. NO la de descarga, que es un enlace firmado
  de S3 que caduca a los 15 minutos.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Final

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

log = structlog.stdlib.get_logger("ingestion.cbp_cross")

BASE: Final = "https://rulings.cbp.gov"
AUTORIDAD: Final = "CBP"
#: Entre petición y petición. Es un servicio público: no se le martilla.
PAUSA_S: Final = 0.4

_CODIGO = re.compile(r"^(\d{4})\.(\d{2})(?:\.\d{2,4})*$")


class ResolucionIlegibleError(ValueError):
    """La API devolvió algo sin los campos mínimos. Se omite y se dice."""


@dataclass(frozen=True)
class ParsedRuling:
    ruling_number: str
    collection: str | None
    ruling_date: date
    subject: str
    categories: str | None
    tariff_codes: tuple[str, ...]
    hs6_codes: tuple[str, ...]
    full_text: str
    is_revoked: bool
    revoked_by: tuple[str, ...]
    modified_by: tuple[str, ...]
    related_rulings: tuple[str, ...]

    @property
    def url(self) -> str:
        return url_publica(self.ruling_number)


def url_publica(numero: str) -> str:
    return f"{BASE}/ruling/{numero}"


def codigos_de(tariffs: str | None) -> tuple[str, ...]:
    """«7323.93.0030, 9903.88.03» → los códigos, sin espacios ni vacíos."""
    return tuple(c.strip() for c in (tariffs or "").split(",") if c.strip())


def hs6_de(codigos: tuple[str, ...]) -> tuple[str, ...]:
    """Los HS6 de los códigos, sin repetir y en orden. Fuera los capítulos 98 y 99."""
    salida: list[str] = []
    for codigo in codigos:
        m = _CODIGO.match(codigo)
        if not m or m.group(1).startswith(("98", "99")):
            continue
        hs6 = m.group(1) + m.group(2)
        if hs6 not in salida:
            salida.append(hs6)
    return tuple(salida)


def _lista(valor: Any) -> tuple[str, ...]:
    if not valor:
        return ()
    return tuple(str(v).strip() for v in valor if str(v).strip())


def _texto(valor: Any) -> str:
    """CBP separa líneas con `\\r`. Se normaliza a `\\n` y se recortan los
    espacios al final de cada línea, sin tocar el contenido."""
    crudo = str(valor or "").replace("\r\n", "\n").replace("\r", "\n")
    lineas = [linea.rstrip() for linea in crudo.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


#: Lo que `/api/ruling/{n}` NO trae y el resumen de `/api/search` sí (20-oct):
#: la HQ 087732 (6912.00.41) sale revocada por la 950390 en la búsqueda y con
#: `revokedBy: null` en el detalle. Cargada sólo del detalle, parecía vigente.
RELACIONES: Final = ("revokedBy", "modifiedBy", "relatedRulings", "operationallyRevoked")


def combinar(detalle: dict[str, Any], resumen: dict[str, Any] | None) -> dict[str, Any]:
    """El detalle, con las relaciones tomadas del resumen de búsqueda cuando el
    detalle no las trae. Lo combinado es lo que va a RAW: la procedencia de cada
    campo queda en el documento guardado."""
    if not resumen:
        return dict(detalle)
    salida = dict(detalle)
    for campo in RELACIONES:
        if not salida.get(campo) and resumen.get(campo):
            salida[campo] = resumen[campo]
    return salida


def parse(detalle: dict[str, Any]) -> ParsedRuling:
    """Del JSON de una resolución (`combinar`) a una resolución."""
    numero = str(detalle.get("rulingNumber") or "").strip()
    fecha = detalle.get("rulingDate")
    asunto = re.sub(r"\s+", " ", str(detalle.get("subject") or "")).strip()
    texto = _texto(detalle.get("text"))
    if not numero or not fecha or not asunto or not texto:
        raise ResolucionIlegibleError(f"resolución sin número, fecha, asunto o texto: {numero!r}")
    codigos = codigos_de(detalle.get("tariffs"))
    revocada_por = _lista(detalle.get("revokedBy"))
    return ParsedRuling(
        ruling_number=numero,
        collection=(str(detalle.get("collection") or "").strip() or None),
        ruling_date=datetime.fromisoformat(str(fecha)).date(),
        subject=asunto,
        categories=(str(detalle.get("categories") or "").strip() or None),
        tariff_codes=codigos,
        hs6_codes=hs6_de(codigos),
        full_text=texto,
        is_revoked=bool(revocada_por) or bool(detalle.get("operationallyRevoked")),
        revoked_by=revocada_por,
        modified_by=_lista(detalle.get("modifiedBy")),
        related_rulings=_lista(detalle.get("relatedRulings")),
    )


def de_la_partida(resumen: dict[str, Any], partida: str) -> bool:
    """¿Alguno de sus códigos cae en la partida (4 dígitos)?"""
    return any(c.replace(".", "").startswith(partida) for c in codigos_de(resumen.get("tariffs")))


def buscar(cliente: httpx.Client, partida: str) -> Iterator[dict[str, Any]]:
    """Los resúmenes que la búsqueda devuelve para la partida, página a página,
    filtrados a los que de verdad citan un código de esa partida."""
    pagina = 1
    while True:
        r = cliente.get(
            f"{BASE}/api/search",
            params={
                "term": partida,
                "collection": "ALL",
                "pageSize": 100,
                "page": pagina,
                "sortBy": "RELEVANCE",
            },
        )
        r.raise_for_status()
        datos = r.json()
        resumenes = datos.get("rulings") or []
        for resumen in resumenes:
            if de_la_partida(resumen, partida):
                yield resumen
        if len(resumenes) < 100 or pagina * 100 >= int(datos.get("totalHits") or 0):
            return
        pagina += 1
        time.sleep(PAUSA_S)


def detalle(cliente: httpx.Client, numero: str) -> bytes:
    """El JSON crudo de la resolución: es lo que va a RAW."""
    r = cliente.get(f"{BASE}/api/ruling/{numero}")
    r.raise_for_status()
    time.sleep(PAUSA_S)
    return r.content
