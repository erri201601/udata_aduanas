"""RAW -> PARSED del preámbulo y el Artículo 1o. de la LIGIE 2022 (texto
vigente, Cámara de Diputados).

Alcance: sólo el preámbulo del decreto y el Artículo 1o. -- la tarifa
completa (partidas, subpartidas, fracciones) ya se carga de otra fuente
(`ingestion.snice.tariff` / `ingestion.snice.tariff_headings`, el PDF que
publica SNICE, no el que publica Diputados). Ambos documentos representan
la misma ley pero son archivos distintos, con su propio `content_hash` --
por eso esto vive en `ingestion.diputados`, no en `ingestion.snice`, aunque
comparten el mismo `LegalDocument` (short_name "LIGIE",
`ingestion.snice.load.get_or_create_ligie_document`).

HALLAZGO (2026-09-23, verificado contra las 893 páginas completas del texto
vigente -- `diputados.gob.mx/LeyesBiblio/pdf/LIGIE_2022.pdf` -- y contra el
decreto original publicado en el DOF el 7 de junio de 2022): ni el
preámbulo ni el Artículo 1o. citan el Sistema Armonizado ni ninguna edición
o enmienda -- cero coincidencias de "Sistema Armonizado", "enmienda" o
"nomenclatura del sistema" en todo el documento. El Artículo 1o. sólo dice
"de conformidad con la siguiente: TARIFA", sin más. `ingestion.diputados.
load` deja esta observación pegada al propio texto cargado (marcada
NEEDS_VALIDATION) para que quien busque ahí no repita la búsqueda -- el
supuesto de si las fracciones son SA 2022 no se cierra con esta fuente
(Ulises, 2026-09-23).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


def extract_text(pdf_path: str) -> list[str]:
    """`pdftotext -layout` sobre la primera página -- ahí caben el preámbulo
    y el Artículo 1o. completos, verificado contra el PDF real (893 páginas,
    ninguna razón para procesar más que la primera)."""
    resultado = subprocess.run(
        ["pdftotext", "-layout", "-f", "1", "-l", "1", pdf_path, "-"],
        capture_output=True,
        check=True,
        text=True,
    )
    return resultado.stdout.splitlines()


@dataclass(frozen=True)
class ParsedArticulo:
    rule_number: str
    heading_text: str
    text: str


#: Arranca justo después del encabezado institucional repetido de cada
#: página ("LEY DE LOS IMPUESTOS...", "CÁMARA DE DIPUTADOS...", "TEXTO
#: VIGENTE"...) -- la fórmula protocolaria del decreto siempre empieza así.
_INICIO_PREAMBULO_RE = re.compile(r"^Al margen un sello")
#: El preámbulo termina en la línea del "Artículo Único" que expide la ley
#: -- lo que sigue es el encabezado repetido del cuerpo de la ley, luego el
#: Artículo 1o.
_FIN_PREAMBULO_RE = re.compile(r"^\s*Art[íi]culo [UÚ]nico\.")
_INICIO_ARTICULO1_RE = re.compile(r"^\s*Art[íi]culo 1o\.-")
#: El Artículo 1o. remite "a la siguiente: TARIFA" -- la palabra TARIFA es
#: el objeto directo de esa misma oración, así que cierra el artículo; lo
#: que sigue ("Sección I...") ya es el cuerpo de la tarifa, no el artículo.
_FIN_ARTICULO1_RE = re.compile(r"^\s*TARIFA\s*$")


def _unir(lineas: list[str]) -> str:
    texto = " ".join(linea.strip() for linea in lineas if linea.strip())
    return " ".join(texto.split())


def parse_preambulo_y_articulo1(lines: list[str]) -> list[ParsedArticulo]:
    """El preámbulo del decreto y el Artículo 1o., como dos `ParsedArticulo`
    -- los únicos elementos de esta carga (ver docstring del módulo)."""
    inicio_preambulo = next(i for i, linea in enumerate(lines) if _INICIO_PREAMBULO_RE.match(linea))
    fin_preambulo = next(
        i
        for i, linea in enumerate(lines)
        if i >= inicio_preambulo and _FIN_PREAMBULO_RE.match(linea)
    )
    inicio_articulo1 = next(
        i
        for i, linea in enumerate(lines)
        if i > fin_preambulo and _INICIO_ARTICULO1_RE.match(linea)
    )
    fin_articulo1 = next(
        i
        for i, linea in enumerate(lines)
        if i >= inicio_articulo1 and _FIN_ARTICULO1_RE.match(linea)
    )

    preambulo = _unir(lines[inicio_preambulo : fin_preambulo + 1])
    articulo1 = _unir(lines[inicio_articulo1 : fin_articulo1 + 1])

    return [
        ParsedArticulo(
            rule_number="PREAMBULO", heading_text="Preámbulo del Decreto", text=preambulo
        ),
        ParsedArticulo(rule_number="1", heading_text="Artículo 1o.", text=articulo1),
    ]
