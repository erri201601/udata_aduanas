"""Troceado de normas mexicanas (§27).

LA UNIDAD ES EL ARTÍCULO, NO EL PÁRRAFO

Un dictamen cita «artículo 36-A, fracción I», no «párrafo tercero de la
página 12». Trocear por longitud fija partiría un artículo a la mitad y
produciría citas que no se pueden verificar contra el documento.

LO QUE HAY QUE RECONOCER, Y POR QUÉ

El DOF no publica texto limpio. Un parser probado sólo contra prosa inventada
falla el día que llega el documento real, así que éste reconoce lo que
realmente aparece:

  Artículo 36-A.-     el guion tras el número, y los sufijos con letra
  I. II. III.         fracciones en romanos, que se citan por separado
  ARTÍCULO SEGUNDO    transitorios, en mayúsculas y ordinal escrito
  (Reformado DOF …)   marcas de reforma, que traen la fecha de vigencia

Las fracciones se emiten como chunks propios además del artículo completo:
se citan solas, así que tienen que poder recuperarse solas.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rag.types import LegalChunk, hash_contenido

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import date

    from rag.types import DataOrigin

#: «Artículo 36-A.-», «ARTÍCULO 1o.», «Art. 59.». El sufijo con letra es real
#: y frecuente: 36-A y 36 son artículos distintos.
_ARTICULO = re.compile(
    r"^\s*(?:art[íi]culo|art\.)\s+(?P<num>\d+[ºo°]?(?:[-\s]?[A-Z])?)\s*\.?\s*[-–.]?\s*",
    re.IGNORECASE | re.MULTILINE,
)

#: «ARTÍCULO PRIMERO», «TRANSITORIO SEGUNDO». Los transitorios fijan cuándo
#: entra en vigor lo demás: perderlos es perder la vigencia.
_TRANSITORIO = re.compile(
    # El "ARTÍCULO" va sin distinguir caja porque el DOF lo publica en
    # mayúsculas, pero el ORDINAL sí se exige en mayúsculas: en minúsculas,
    # "primero" y "segundo" aparecen en prosa corriente y partirían artículos
    # por la mitad.
    r"^\s*(?:(?i:art[íi]culo)\s+)?(?P<ord>PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|"
    r"S[ÉE]PTIMO|OCTAVO|NOVENO|D[ÉE]CIMO)\s*\.?\s*[-–.]?\s*",
    re.MULTILINE,
)

#: «I.», «XIV.» al principio de línea. Una fracción se cita sola.
_FRACCION = re.compile(r"^\s*(?P<rom>[IVXLC]+)\.\s+", re.MULTILINE)

#: «(Reformado mediante Decreto publicado en el DOF el 25-06-2018)». Cuando
#: aparece, esa es la fecha desde la que rige ESE texto, no la del documento.
_REFORMA = re.compile(
    r"reformad[oa].{0,80}?DOF.{0,20}?(?P<fecha>\d{1,2}[-/]\d{1,2}[-/]\d{4})",
    re.IGNORECASE | re.DOTALL,
)

#: Encabezados de jerarquía, para reconstruir el `path` de cada artículo.
_JERARQUIA = re.compile(
    r"^\s*(?P<nivel>T[ÍI]TULO|CAP[ÍI]TULO|SECCI[ÓO]N)\s+(?P<id>[^\n]{1,60})$",
    re.IGNORECASE | re.MULTILINE,
)


def _fecha_de_reforma(texto: str, por_defecto: date) -> date:
    """La fecha de reforma del propio texto, o la del documento si no la trae."""
    encontrada = _REFORMA.search(texto)
    if not encontrada:
        return por_defecto

    crudo = encontrada.group("fecha").replace("/", "-")
    dia, mes, anio = (int(p) for p in crudo.split("-"))
    from datetime import date as _date

    try:
        return _date(anio, mes, dia)
    except ValueError:
        # Una fecha imposible en el texto no invalida el artículo: se usa la
        # del documento y se sigue. Inventar una sería peor.
        return por_defecto


def _fracciones(articulo: str) -> Iterator[tuple[str, str]]:
    """(romano, texto) de cada fracción del artículo."""
    marcas = list(_FRACCION.finditer(articulo))
    for i, marca in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(articulo)
        cuerpo = articulo[marca.end() : fin].strip()
        if cuerpo:
            yield marca.group("rom"), cuerpo


def _path(texto: str, hasta: int) -> str | None:
    """Jerarquía acumulada hasta esa posición: «Título Tercero > Capítulo Único»."""
    niveles: dict[str, str] = {}
    for marca in _JERARQUIA.finditer(texto[:hasta]):
        niveles[marca.group("nivel").upper()] = (
            f"{marca.group('nivel').strip()} {marca.group('id').strip()}"
        )
    return " > ".join(niveles.values()) or None


def trocear(
    texto: str,
    *,
    document: str,
    data_origin: DataOrigin,
    valid_from: date,
    source_id: object | None = None,
    document_id: object | None = None,
    published_at: date | None = None,
    url: str | None = None,
    incluir_fracciones: bool = True,
) -> list[LegalChunk]:
    """Trocea una norma en chunks citables.

    `data_origin` es obligatorio y viaja a cada chunk: es lo que impide que un
    fixture acabe contando como fundamento jurídico.

    `valid_from` es el del documento y actúa de respaldo. Cuando un artículo
    trae su marca de reforma, gana la del artículo — que es el punto de tener
    vigencia por chunk.
    """
    marcas = [(m, False) for m in _ARTICULO.finditer(texto)]
    marcas += [(m, True) for m in _TRANSITORIO.finditer(texto)]
    marcas.sort(key=lambda par: par[0].start())

    chunks: list[LegalChunk] = []
    for i, (marca, es_transitorio) in enumerate(marcas):
        fin = marcas[i + 1][0].start() if i + 1 < len(marcas) else len(texto)
        cuerpo = texto[marca.end() : fin].strip()
        if not cuerpo:
            continue

        identificador = (
            f"Transitorio {marca.group('ord').title()}"
            if es_transitorio
            else marca.group("num").replace(" ", "").upper()
        )
        desde = _fecha_de_reforma(cuerpo, valid_from)
        comun = {
            "source_id": source_id,
            "document_id": document_id,
            "document": document,
            "data_origin": data_origin,
            "valid_from": desde,
            "published_at": published_at,
            "url": url,
            "path": _path(texto, marca.start()),
        }

        chunks.append(
            LegalChunk(
                article=identificador, text=cuerpo, content_hash=hash_contenido(cuerpo), **comun
            )  # type: ignore[arg-type]
        )

        if incluir_fracciones and not es_transitorio:
            for romano, fragmento in _fracciones(cuerpo):
                chunks.append(
                    LegalChunk(
                        article=f"{identificador} fracción {romano}",
                        text=fragmento,
                        content_hash=hash_contenido(fragmento),
                        **comun,  # type: ignore[arg-type]
                    )
                )

    return chunks
