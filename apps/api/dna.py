"""Carga el Product DNA vigente de un producto y lo deja listo para el motor.

Vive fuera de los routers porque lo necesitan dos: el que clasifica un producto
suelto y el que revisa un pedimento completo. Duplicarlo habría duplicado
también el detalle del `locator`, que es fácil de perder y cambia el resultado.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import sqlalchemy as sa
from core.product_dna import ExtractedAttribute, ProductDnaDraft
from database.models import ProductAttribute, ProductDna

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

#: Tope de términos de búsqueda. Más que esto ensancha la consulta a la
#: nomenclatura hasta que deja de discriminar.
MAX_TERMINOS = 6


def cargar_borrador(session: Session, product_id: uuid.UUID) -> ProductDnaDraft | None:
    """El Product DNA vigente del producto, o `None` si no tiene.

    `None` no es un error: significa que nadie ha extraído todavía los
    atributos de ese producto, y quien llame decide si eso es un 409 o una
    partida que no se puede verificar.
    """
    fila = session.scalars(
        sa.select(ProductDna)
        .where(ProductDna.product_id == product_id, ProductDna.is_current.is_(True))
        .order_by(ProductDna.version.desc())
    ).first()
    if fila is None:
        return None

    atributos = session.scalars(
        sa.select(ProductAttribute).where(ProductAttribute.product_dna_id == fila.id)
    ).all()

    return ProductDnaDraft(
        summary=fila.summary,
        missing_information=tuple(fila.missing_information or ()),
        input_kinds=tuple(fila.input_kinds or ()),
        attributes=tuple(
            ExtractedAttribute(
                name=a.name,
                value=a.value,
                unit=a.unit,
                status=a.status,  # type: ignore[arg-type]
                confidence=a.confidence,
                # `locator` no se persiste: los estados ya vienen saneados de
                # cuando se extrajo, así que rehacer el saneamiento aquí los
                # degradaría una segunda vez sin motivo.
                locator=a.value,
            )
            for a in atributos
        ),
    )


def version_vigente(session: Session, product_id: uuid.UUID) -> ProductDna | None:
    """La fila del DNA vigente, cuando hace falta su id y no sólo su contenido."""
    return session.scalars(
        sa.select(ProductDna)
        .where(ProductDna.product_id == product_id, ProductDna.is_current.is_(True))
        .order_by(ProductDna.version.desc())
    ).first()


def terminos(dna: ProductDnaDraft) -> list[str]:
    """Términos de búsqueda a partir de lo sólido del Product DNA.

    Sólo lo observado o extraído: buscar en la nomenclatura con un dato
    inferido llevaría al motor por una vía que nadie leyó en el documento.

    PALABRAS SUELTAS, NO FRASES NI NÚMEROS

    El prefiltro del catálogo es un `ILIKE '%término%'` sobre la descripción de
    la fracción, así que el término tiene que ser algo que aparezca literal en
    el texto de la tarifa. Medido contra las 1 445 fracciones cargadas:

        'portátil'              →   9 fracciones
        'procesamiento'         →   9
        'pulgadas'              →   5
        'tratamiento de datos'  →   0   ← la tarifa dice "tratamiento o
                                          procesamiento de datos"
        '8 GB' / '1.4 kg'       →   0
        'laptop'                →   0   ← la tarifa nunca dice "laptop"

    Antes se pasaba el resumen completo como un solo término —que no coincide
    con nada— y los valores de atributo pelados: `"8"` y `"1.4"`. Esos dos sí
    coincidían, con las 25 partidas que mencionan un 8 o un 1.4 por cualquier
    motivo, y de ahí RGI 3 c) —«la última en orden numérico»— resolvía a 8539
    (lámparas) para una computadora portátil. La regla se aplicó bien; lo que
    estaba mal eran los candidatos (Persona 1, 2026-09-08).

    Por eso se tokeniza y se descarta lo que no discrimina: números sueltos y
    palabras demasiado cortas, que engancharían media tarifa.
    """
    vistos: set[str] = set()
    encontrados: list[str] = []

    def agregar(palabra: str) -> None:
        clave = palabra.casefold()
        if clave in vistos:
            return
        vistos.add(clave)
        encontrados.append(palabra)

    for texto in (dna.summary or "", *(a.value or "" for a in dna.solid())):
        for palabra in _palabras(texto):
            agregar(palabra)

    return encontrados[:MAX_TERMINOS]


def palabras_de(dna: ProductDnaDraft) -> list[str]:
    """Todas las palabras distintivas de la ficha, SIN truncar.

    `terminos()` corta a `MAX_TERMINOS` y hace bien: más términos ensanchan la
    consulta hasta que deja de discriminar. Pero quien busca equivalencias de
    vocabulario necesita verlas todas, porque la palabra que casa con un puente
    puede estar más allá del corte.

    Pasó con la tubería del corpus: su ficha dice «para conducción de fluidos»
    y esas dos palabras caían en la posición 10 y 11 de la lista. El puente que
    las traduce a «oleoductos o gasoductos» no podía dispararse nunca.
    """
    vistas: set[str] = set()
    salida: list[str] = []
    for texto in (dna.summary or "", *(a.value or "" for a in dna.solid())):
        for palabra in _palabras(texto):
            if palabra.casefold() not in vistas:
                vistas.add(palabra.casefold())
                salida.append(palabra)
    return salida


#: Por debajo de esto una palabra engancha demasiadas fracciones para servir de
#: filtro: "de", "con", "kg", "RAM".
MIN_LONGITUD_TERMINO = 5


def _palabras(texto: str) -> list[str]:
    """Palabras del texto que pueden discriminar en la tarifa."""
    crudas = re.findall(r"[^\W\d_]+", texto, flags=re.UNICODE)
    return [p for p in crudas if len(p) >= MIN_LONGITUD_TERMINO]
