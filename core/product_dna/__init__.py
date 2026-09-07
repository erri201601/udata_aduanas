"""Product DNA Engine — describe una mercancía sin inventar nada (§16).

Primer eslabón del vertical slice de §42: sin Product DNA no hay nada que
clasificar. Lo que produce alimenta al RGI Engine, que pesa distinto un hecho
observado y uno inferido.

USO

    from core.llm import get_default_provider
    from core.product_dna import LlmExtractor, SourceDocument, extract

    extractor = LlmExtractor(get_default_provider())
    borrador = extract(
        SourceDocument(text=ficha, kind="datasheet", reference="ficha.pdf"),
        extractor=extractor,
    )

    borrador.solid()                # sostienen una clasificación
    borrador.missing_information    # lo que falta, críticos primero
    extractor.last_metadata         # trazabilidad para construir la evidencia

LA REGLA QUE JUSTIFICA EL MÓDULO

Un dato ausente produce `MISSING`, nunca un valor plausible. Si el motor
rellenara el voltaje de un aparato porque «suele ser 220 V», esa invención
viajaría al RGI Engine, de ahí a una fracción arancelaria y de ahí a un
pedimento, indistinguible de un dato real.

El saneamiento de `engine.py` se aplica siempre, venga la extracción de un
modelo o de un fixture. El prompt le prohíbe al modelo inventar; prohibirlo no
es garantizarlo.

QUÉ NO HACE ESTA VERSIÓN

No emite `EvidenceRecord` — igual que el RGI Engine. Produce el borrador y
expone la metadata de la llamada; quien orquesta construye la evidencia con
`core.evidence.builder.model_output()`. Así el motor se prueba sin base de
datos y `core/` no importa persistencia (§29).

Tampoco lee PDF ni imágenes: recibe texto ya extraído. Lo multimodal es la
tarea 3 del backlog.
"""

from __future__ import annotations

from core.product_dna.attributes import (
    ATTRIBUTE_STATUSES,
    CATALOG,
    CRITICOS,
    SOLID_STATUSES,
    AttributeStatus,
    es_critico,
)
from core.product_dna.engine import extract
from core.product_dna.llm_extractor import PROMPT_ID, PROMPT_VERSION, LlmExtractor
from core.product_dna.ports import Extractor
from core.product_dna.types import ExtractedAttribute, ProductDnaDraft, SourceDocument

__all__ = [
    "ATTRIBUTE_STATUSES",
    "CATALOG",
    "CRITICOS",
    "PROMPT_ID",
    "PROMPT_VERSION",
    "SOLID_STATUSES",
    "AttributeStatus",
    "ExtractedAttribute",
    "Extractor",
    "LlmExtractor",
    "ProductDnaDraft",
    "SourceDocument",
    "es_critico",
    "extract",
]
