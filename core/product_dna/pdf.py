"""El texto de un PDF, página a página, para el extractor de texto (§16).

UN PDF NO ES UNA IMAGEN, Y TAMPOCO SE LE MANDA AL MODELO

Se saca su capa de texto y se pasa por el mismo `LlmExtractor` que una ficha
pegada. `ModelProvider` no se toca (Persona 1, 13-oct): mandar el PDF entero
exigiría ampliar el contrato central, y para una ficha técnica con texto no
aporta nada que la capa de texto no tenga.

CADA PÁGINA LLEVA SU MARCA

El texto que recibe el modelo va con `[p.N]` delante de cada página, para que
pueda decir DÓNDE encontró cada dato. Sin la marca, «evidence_reference» sólo
podría citar un fragmento, y en un datasheet de veinte páginas encontrarlo es
volver a leerlo entero.

SIN TEXTO NO HAY FICHA, Y SE DICE

Un PDF escaneado no tiene capa de texto. No hay OCR, así que la respuesta es
explícita —«sin texto extraíble»— en vez de pasarle al modelo una cadena vacía
que devolvería una ficha vacía con apariencia de lectura.
"""

from __future__ import annotations

import io
from typing import Final

from pypdf import PdfReader
from pypdf.errors import PyPdfError

#: Una ficha técnica larga son decenas de páginas. Más que esto es un manual
#: entero, y el modelo lo truncaría por su cuenta sin decir dónde.
MAXIMO_CARACTERES: Final = 120_000

SIN_TEXTO: Final = "sin texto extraíble"


class SinTextoExtraibleError(ValueError):
    """El PDF no trae capa de texto: hace falta OCR, y no lo hay."""


class PdfIlegibleError(ValueError):
    """No es un PDF, está dañado o está cifrado."""


class PdfDemasiadoLargoError(ValueError):
    """El texto pasa de `MAXIMO_CARACTERES`."""


def texto_con_paginas(datos: bytes) -> str:
    """El texto del PDF con `[p.N]` delante de cada página que tenga texto.

    Las páginas sin texto se saltan sin marca —una portada con sólo una foto no
    aporta nada que citar—, pero la numeración es la del documento: «[p.3]» es
    la tercera página del PDF, la cuente quien la cuente.
    """
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            raise PdfIlegibleError("el PDF está cifrado")
        paginas = [
            (n, (pagina.extract_text() or "").strip()) for n, pagina in enumerate(lector.pages, 1)
        ]
    # `PyPdfError` es la base de los errores de pypdf; un archivo dañado también
    # puede salir como `ValueError` desde dentro del parser.
    except (PyPdfError, ValueError) as exc:
        raise PdfIlegibleError(f"no se pudo leer el PDF: {exc}") from exc

    trozos = [f"[p.{n}]\n{texto}" for n, texto in paginas if texto]
    if not trozos:
        raise SinTextoExtraibleError(
            f"{SIN_TEXTO}: ninguna de sus {len(paginas)} páginas tiene capa de texto "
            "(¿es un escaneo?). No hay OCR."
        )

    texto = "\n\n".join(trozos)
    if len(texto) > MAXIMO_CARACTERES:
        raise PdfDemasiadoLargoError(
            f"el PDF tiene {len(texto)} caracteres de texto y el máximo son "
            f"{MAXIMO_CARACTERES}: sube la ficha técnica, no el manual entero"
        )
    return texto
