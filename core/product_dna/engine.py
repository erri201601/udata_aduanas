"""Product DNA Engine — describe una mercancía sin inventar nada.

Primer eslabón del §42: sin Product DNA no hay nada que clasificar. Lo que este
motor produce alimenta al RGI Engine, que trata distinto un hecho observado y
uno inferido.

LA REGLA QUE JUSTIFICA TODO EL MÓDULO

Un dato ausente produce `MISSING`, nunca un valor plausible. No es una
preferencia de estilo: si el motor rellenara el voltaje de un aparato porque
«suele ser 220 V», esa invención viajaría al RGI Engine, de ahí a una fracción
arancelaria, y de ahí a un pedimento. El error sería indistinguible de un dato
real y llegaría hasta la autoridad.

Por eso el saneamiento no confía en el extractor. Un modelo puede marcar como
`OBSERVED` algo que dedujo, o rellenar un campo para que el JSON se vea
completo — el prompt se lo prohíbe, pero prohibirlo no es garantizarlo. Estas
reglas se aplican SIEMPRE, venga la extracción de donde venga:

1. Sin valor no hay atributo: pasa a `MISSING`, sin confianza ni localización.
2. `OBSERVED` y `EXTRACTED` exigen localización en el documento. Sin ella el
   dato no se extrajo de ahí — se dedujo, y baja a `INFERRED`.
3. `INFERRED` exige confianza explícita. Una deducción sin confianza declarada
   se presenta igual que un hecho, que es justo lo que no puede pasar.
4. El catálogo de §16 se devuelve completo. Lo que el extractor no mencionó
   sale `MISSING`, porque un atributo que nadie buscó y uno que no está deben
   distinguirse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from core.product_dna.attributes import CATALOG, SOLID_STATUSES, UNIDADES, es_critico
from core.product_dna.types import ExtractedAttribute, ProductDnaDraft

if TYPE_CHECKING:
    from core.product_dna.ports import Extractor
    from core.product_dna.types import SourceDocument

log = structlog.stdlib.get_logger("core.product_dna")


def _sanear(attr: ExtractedAttribute) -> ExtractedAttribute:
    """Aplica las cuatro reglas a un atributo. Nunca sube su categoría."""
    vacio = not (attr.value and attr.value.strip())
    if vacio:
        return ExtractedAttribute(name=attr.name, status="MISSING")

    status = attr.status
    confidence = attr.confidence

    # Regla 2: lo que no se puede localizar no se extrajo, se dedujo.
    if status in SOLID_STATUSES and not attr.locator:
        log.info("product_dna.degradado", attribute=attr.name, de=status, a="INFERRED")
        status = "INFERRED"

    # Regla 3: una deducción sin confianza declarada se lee como un hecho.
    if status == "INFERRED" and confidence is None:
        log.info("product_dna.inferido_sin_confianza", attribute=attr.name)
        return ExtractedAttribute(name=attr.name, status="MISSING")

    return ExtractedAttribute(
        name=attr.name,
        value=attr.value.strip() if attr.value else None,
        unit=attr.unit or UNIDADES.get(attr.name),
        status=status,
        confidence=confidence,
        locator=attr.locator,
    )


def extract(document: SourceDocument, *, extractor: Extractor) -> ProductDnaDraft:
    """Extrae el Product DNA de un documento.

    Devuelve siempre los 18 atributos de §16. `missing_information` enumera lo
    que un clasificador necesitaría y el documento no aporta, con los críticos
    primero: son los que impiden clasificar, no los que sólo empobrecen la
    descripción.
    """
    propuesta = extractor.extract(document)
    propuestos = {a.name: a for a in propuesta.attributes}

    atributos = tuple(
        _sanear(propuestos.get(nombre, ExtractedAttribute(name=nombre))) for nombre in CATALOG
    )

    faltantes = tuple(a.name for a in atributos if a.status == "MISSING")
    # Los críticos primero: son los que bloquean la clasificación.
    faltantes = tuple(sorted(faltantes, key=lambda n: (not es_critico(n), CATALOG.index(n))))

    log.info(
        "product_dna.extraido",
        input_kind=document.kind,
        total=len(atributos),
        solidos=sum(1 for a in atributos if a.is_solid),
        inferidos=sum(1 for a in atributos if a.status == "INFERRED"),
        faltantes=len(faltantes),
        criticos_faltantes=[n for n in faltantes if es_critico(n)],
    )

    return ProductDnaDraft(
        attributes=atributos,
        summary=propuesta.summary,
        missing_information=faltantes,
        input_kinds=(document.kind,),
    )
