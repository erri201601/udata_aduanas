"""Extractor apoyado en un modelo de lenguaje.

Es una implementación del puerto `Extractor`, no el motor. Todo lo que decide
si un dato es utilizable vive en `engine.py` y se aplica igual venga la
extracción de aquí o de un fixture: el prompt le prohíbe al modelo inventar,
pero prohibirlo no es garantizarlo.

El motor no emite evidencia, igual que el RGI Engine: produce el borrador y
expone la metadata de la llamada. Quien orquesta construye la evidencia con
`core.evidence.builder.model_output()` y la enlaza a cada atributo. Así el
motor sigue siendo probable sin base de datos.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.llm import Message
from core.product_dna.attributes import CATALOG
from core.product_dna.types import ExtractedAttribute, ProductDnaDraft
from core.prompts import load_prompt

if TYPE_CHECKING:
    from core.llm.base import ModelProvider
    from core.llm.types import CallMetadata
    from core.product_dna.types import SourceDocument

PROMPT_ID = "product_dna.extract"
#: Fijar la versión es deliberado: un cambio de prompt cambia las salidas, y
#: subir de versión sin querer haría irreproducible todo lo extraído antes.
PROMPT_VERSION = "0.1"


class _AtributoLLM(BaseModel):
    """Un atributo tal y como lo devuelve el modelo, antes de sanear."""

    name: str
    value: str | None = None
    unit: str | None = None
    status: str = "MISSING"
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    evidence_reference: str | None = None
    """Localización en el documento: página, sección o fragmento citado."""


class _ExtraccionLLM(BaseModel):
    """Salida estructurada del prompt `product_dna.extract`."""

    summary: str | None = None
    attributes: list[_AtributoLLM] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class LlmExtractor:
    """Extrae Product DNA con un `ModelProvider`.

    `last_metadata` guarda la trazabilidad de la última llamada —proveedor,
    modelo, versión de prompt, tokens y latencia— para que quien orqueste pueda
    construir la evidencia sin repetir la llamada.
    """

    def __init__(self, provider: ModelProvider, *, max_attempts: int = 2) -> None:
        self._provider = provider
        self._max_attempts = max_attempts
        self.last_metadata: CallMetadata | None = None

    def extract(self, document: SourceDocument) -> ProductDnaDraft:
        """Pide al modelo los atributos del documento."""
        prompt = load_prompt(PROMPT_ID, PROMPT_VERSION)
        respuesta = self._provider.generate_structured(
            [Message(role="user", content=prompt.render(documento=document.text))],
            _ExtraccionLLM,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            max_attempts=self._max_attempts,
        )
        self.last_metadata = respuesta.metadata

        return ProductDnaDraft(
            summary=respuesta.data.summary,
            # Un nombre fuera de §16 se descarta aquí: el catálogo es cerrado y
            # un atributo inventado no tiene columna donde caer.
            attributes=tuple(
                ExtractedAttribute(
                    name=a.name,
                    value=a.value,
                    unit=a.unit,
                    status=a.status,  # type: ignore[arg-type]
                    confidence=a.confidence,
                    locator=a.evidence_reference,
                )
                for a in respuesta.data.attributes
                if a.name in CATALOG
                and a.status in {"OBSERVED", "EXTRACTED", "INFERRED", "MISSING"}
            ),
        )
