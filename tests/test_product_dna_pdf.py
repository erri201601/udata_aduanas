"""El texto de un PDF para el extractor de Product DNA (§16).

`pdf_de_prueba` fabrica un PDF mínimo a mano —una página por elemento, `None`
para una página sin capa de texto— para no versionar binarios en el repo. Lo
reutilizan los tests del endpoint.
"""

from __future__ import annotations

import pytest
from core.product_dna.pdf import (
    MAXIMO_CARACTERES,
    SIN_TEXTO,
    PdfDemasiadoLargoError,
    PdfIlegibleError,
    SinTextoExtraibleError,
    texto_con_paginas,
)

pytestmark = pytest.mark.unit


def pdf_de_prueba(paginas: list[str | None]) -> bytes:
    """Un PDF válido con Helvetica; `None` es una página sin texto (un escaneo)."""
    objetos = ["<< /Type /Catalog /Pages 2 0 R >>"]
    n = len(paginas)
    hijos = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objetos.append(f"<< /Type /Pages /Kids [{hijos}] /Count {n} >>")
    fuente = 3 + 2 * n
    for i, texto in enumerate(paginas):
        contenido = "" if texto is None else f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET"
        objetos.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {fuente} 0 R >> >> /Contents {4 + 2 * i} 0 R >>"
        )
        objetos.append(f"<< /Length {len(contenido)} >>\nstream\n{contenido}\nendstream")
    objetos.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    salida = b"%PDF-1.4\n"
    posiciones = []
    for k, objeto in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f"{k} 0 obj\n{objeto}\nendobj\n".encode("latin-1")
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    for posicion in posiciones:
        salida += f"{posicion:010d} 00000 n \n".encode()
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return salida


def test_cada_pagina_lleva_su_marca() -> None:
    """Sin la marca, el modelo no puede decir en qué página vio el dato."""
    texto = texto_con_paginas(pdf_de_prueba(["Cable de acero 6x36", "Diametro 10 mm"]))
    assert texto == "[p.1]\nCable de acero 6x36\n\n[p.2]\nDiametro 10 mm"


def test_la_numeracion_es_la_del_documento() -> None:
    """Una portada sin texto no corre la numeración: [p.3] es la tercera página."""
    texto = texto_con_paginas(pdf_de_prueba(["Portada", None, "Voltaje 127 V"]))
    assert "[p.2]" not in texto
    assert "[p.3]\nVoltaje 127 V" in texto


def test_un_escaneo_dice_sin_texto_extraible() -> None:
    """No hay OCR, y una cadena vacía al modelo daría una ficha vacía con
    apariencia de lectura."""
    with pytest.raises(SinTextoExtraibleError, match=SIN_TEXTO):
        texto_con_paginas(pdf_de_prueba([None, None]))


def test_un_pdf_danado_se_dice_ilegible() -> None:
    with pytest.raises(PdfIlegibleError):
        texto_con_paginas(b"%PDF-1.4 esto no es un pdf")


def test_un_manual_entero_no_pasa() -> None:
    largo = "a" * 2000
    paginas: list[str | None] = [largo] * (MAXIMO_CARACTERES // 2000 + 2)
    with pytest.raises(PdfDemasiadoLargoError):
        texto_con_paginas(pdf_de_prueba(paginas))
