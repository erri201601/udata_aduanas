"""EBTI: información arancelaria vinculante de la UE como casos comparables (ADR 0020).

LA FUENTE

La Comisión publica cada día un ZIP con un CSV de las BTI emitidas o
invalidadas ese día (`daily_publications.jsp`, y se descarga por
`ebti_export_management.jsp?publicationDate=…&message=extract`, con una
redirección y una cookie). La página lista las del último mes. No hay forma
estable de bajar el histórico completo: la búsqueda y «Download All BTIs»
dependen del JavaScript de la página. Por eso se cargan las diarias
disponibles y un timer diario acumula las siguientes.

QUÉ ES CADA FILA

Una BTI: referencia, país emisor, vigencia (normalmente tres años), código NC
de 8 a 10 dígitos, la mercancía descrita y la justificación de su
clasificación, en el idioma del país emisor. `STATUS` dice si sigue válida;
`INVALIDATION_REASON` es un código numérico cuyo catálogo no viene en el
archivo: se guarda tal cual, sin inventarle un significado.

Como en CBP (ADR 0019): casos comparables, nunca fundamento. Sólo la HS6 se
compara con México, y la NC no se traduce a TIGIE.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

AUTORIDAD: Final = "EBTI"
BASE: Final = "https://ec.europa.eu/taxation_customs/dds2/ebti"

ETIQUETA_DESCRIPCION: Final = "DESCRIPCIÓN DE LA MERCANCÍA:"
ETIQUETA_JUSTIFICACION: Final = "JUSTIFICACIÓN DE LA CLASIFICACIÓN:"

#: Encabezado del CSV tal como lo publica la Comisión (con su errata en
#: «DATE_OF _ISSUE»). Si cambia, se para: leer columnas corridas sería peor.
COLUMNAS: Final = (
    "BTI_REFERENCE",
    "ISSUING_COUNTRY",
    "START_DATE_OF_VALIDITY",
    "END_DATE_OF_VALIDITY",
    "NOMENCLATURE_CODE",
    "CLASSIFICATION_JUSTIFICATION",
    "STATUS",
    "INVALIDATION_REASON",
    "INVALIDATION_JUSTIFICATION",
    "LANGUAGE",
    "PLACE_OF_ISSUE",
    "DATE_OF _ISSUE",
    "NAME_AND_ADDRESS",
    "DESCRIPTION_OF_GOODS",
    "KEYWORDS",
)

_PUBLICACION = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*</td>\s*<td[^>]*>\s*(EBTI_\d{8}_\d{6}\.zip)", re.S
)


class CsvIlegibleError(ValueError):
    """El CSV no tiene las columnas que este parser conoce."""


@dataclass(frozen=True)
class ParsedBti:
    referencia: str
    pais: str
    idioma: str | None
    emitida: date
    desde: date
    hasta: date | None
    codigo_nc: str
    hs6: str | None
    descripcion: str
    justificacion: str
    palabras_clave: str | None
    valida: bool
    motivo_invalidacion: str | None
    justificacion_invalidacion: str | None

    @property
    def url(self) -> str:
        return f"{BASE}/ebti_details.jsp?showHeader=false&Lang=en&reference={self.referencia}"

    @property
    def asunto(self) -> str:
        """Lo que se lee en la lista: el inicio de la descripción."""
        plano = " ".join(self.descripcion.split())
        return plano if len(plano) <= 300 else plano[:300].rsplit(" ", 1)[0] + " …"

    @property
    def texto(self) -> str:
        """Descripción y justificación, verbatim, bajo etiquetas nuestras."""
        partes = [
            f"{ETIQUETA_DESCRIPCION}\n{self.descripcion.strip()}",
            f"{ETIQUETA_JUSTIFICACION}\n{self.justificacion.strip()}",
        ]
        if self.palabras_clave:
            partes.append(f"PALABRAS CLAVE: {self.palabras_clave.strip()}")
        return "\n\n".join(partes)

    @property
    def categorias(self) -> str:
        """Lo que no tiene columna propia en `comparable_rulings`."""
        datos = [f"idioma={self.idioma or '?'}", f"estado={'VALID' if self.valida else 'INVALID'}"]
        if self.motivo_invalidacion:
            datos.append(f"motivo_invalidacion={self.motivo_invalidacion}")
        return "; ".join(datos)


def _fecha(valor: str) -> date | None:
    valor = (valor or "").strip()
    return datetime.fromisoformat(valor).date() if valor else None


def codigo_de(nomenclatura: str) -> str:
    """«73079100**************» → «73079100». Los asteriscos son relleno."""
    return re.sub(r"\D", "", nomenclatura.split("*", 1)[0])


def parse_csv(texto: str) -> list[ParsedBti]:
    """Las BTI de un CSV diario. Una fila sin referencia, fecha o código se
    omite: no hay cómo identificarla ni con qué compararla."""
    lector = csv.DictReader(io.StringIO(texto.lstrip("﻿")))
    if tuple(lector.fieldnames or ()) != COLUMNAS:
        raise CsvIlegibleError(f"columnas inesperadas: {lector.fieldnames!r}")
    salida: list[ParsedBti] = []
    for fila in lector:
        referencia = (fila["BTI_REFERENCE"] or "").strip()
        codigo = codigo_de(fila["NOMENCLATURE_CODE"] or "")
        emitida = _fecha(fila["DATE_OF _ISSUE"]) or _fecha(fila["START_DATE_OF_VALIDITY"])
        desde = _fecha(fila["START_DATE_OF_VALIDITY"]) or emitida
        if not referencia or len(codigo) < 6 or emitida is None or desde is None:
            continue
        salida.append(
            ParsedBti(
                referencia=referencia,
                pais=(fila["ISSUING_COUNTRY"] or "").strip(),
                idioma=(fila["LANGUAGE"] or "").strip() or None,
                emitida=emitida,
                desde=desde,
                hasta=_fecha(fila["END_DATE_OF_VALIDITY"]),
                codigo_nc=codigo,
                hs6=codigo[:6] if not codigo.startswith(("98", "99")) else None,
                descripcion=fila["DESCRIPTION_OF_GOODS"] or "",
                justificacion=fila["CLASSIFICATION_JUSTIFICATION"] or "",
                palabras_clave=(fila["KEYWORDS"] or "").strip() or None,
                valida=(fila["STATUS"] or "").strip().upper() == "VALID",
                motivo_invalidacion=(fila["INVALIDATION_REASON"] or "").strip() or None,
                justificacion_invalidacion=(fila["INVALIDATION_JUSTIFICATION"] or "").strip()
                or None,
            )
        )
    return salida


def publicaciones(html: str) -> list[tuple[str, str]]:
    """`(fecha_de_publicación, archivo)` de la página de diarias, de la más
    antigua a la más reciente: así una invalidación posterior gana."""
    return sorted(set(_PUBLICACION.findall(html)))
