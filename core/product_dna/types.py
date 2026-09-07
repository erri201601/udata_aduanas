"""Tipos del Product DNA Engine.

`ExtractedAttribute` es lo que produce el motor y lo que consumen dos sitios
distintos: la persistencia (`intelligence.product_attributes`) y el RGI Engine
(`ProductFact`). Ninguno se importa desde aquí — se exponen dos mapeos planos,
igual que `to_canonical_fields()` en `core/llm` y `to_record_fields()` en
`core/evidence`. `core/` no importa persistencia (§29), y dos motores del
dominio no deben depender el uno del otro.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.product_dna.attributes import SOLID_STATUSES, AttributeStatus


class SourceDocument(BaseModel):
    """Lo que se le da al motor para extraer.

    `kind` viaja hasta `ProductDna.input_kinds`: saber si un dato salió de una
    factura o de un datasheet cambia cuánto se puede confiar en él.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    kind: str = "text"
    """text | pdf | image | invoice | datasheet | manual (§16)."""
    reference: str | None = None
    """Nombre de archivo o identificador, para poder citarlo en la evidencia."""


class ExtractedAttribute(BaseModel):
    """Un atributo con su valor y, sobre todo, de dónde salió.

    `locator` es la localización exacta dentro del documento. Sin él un
    atributo no puede ser `OBSERVED` ni `EXTRACTED`: si nadie puede volver al
    documento y verlo, no se extrajo de ahí — se dedujo.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    value: str | None = None
    unit: str | None = None
    status: AttributeStatus = "MISSING"
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    locator: str | None = None

    @property
    def is_known(self) -> bool:
        """¿Aporta información? `MISSING` y los valores vacíos, no."""
        return self.status != "MISSING" and bool(self.value and self.value.strip())

    @property
    def is_solid(self) -> bool:
        """¿Se puede sostener una clasificación sobre este atributo?

        Sólo lo observado o extraído del documento. Lo inferido acompaña.
        """
        return self.is_known and self.status in SOLID_STATUSES

    def to_fact_fields(self) -> dict[str, Any]:
        """Mapeo hacia `ProductFact` del RGI Engine.

        Se entrega como dict para que los dos motores no se importen entre sí.
        El orquestador ensambla: `ProductFact(**attr.to_fact_fields())`.
        """
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
        }

    def to_attribute_fields(self) -> dict[str, Any]:
        """Mapeo hacia las columnas de `intelligence.product_attributes`.

        `evidence_reference` no viaja aquí: es el id de una fila que todavía no
        existe cuando el motor termina. Lo pone quien persiste, después de
        insertar la evidencia.
        """
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "confidence": self.confidence,
        }


class ProductDnaDraft(BaseModel):
    """Resultado del motor: el DNA antes de persistirse.

    Se llama *draft* porque todavía no tiene identidad en la base ni evidencia
    insertada. El motor describe la mercancía; convertir eso en filas es
    trabajo de quien orquesta.
    """

    model_config = ConfigDict(frozen=True)

    attributes: tuple[ExtractedAttribute, ...] = ()
    summary: str | None = None
    missing_information: tuple[str, ...] = ()
    input_kinds: tuple[str, ...] = ()

    def get(self, name: str) -> ExtractedAttribute | None:
        """El atributo por nombre, o `None` si no está en el catálogo."""
        return next((a for a in self.attributes if a.name == name), None)

    def known(self) -> tuple[ExtractedAttribute, ...]:
        """Los que aportan algo."""
        return tuple(a for a in self.attributes if a.is_known)

    def solid(self) -> tuple[ExtractedAttribute, ...]:
        """Los que pueden sostener una clasificación."""
        return tuple(a for a in self.attributes if a.is_solid)

    def missing(self) -> tuple[ExtractedAttribute, ...]:
        """Los que el documento no aportó."""
        return tuple(a for a in self.attributes if a.status == "MISSING")

    def to_dna_fields(self) -> dict[str, Any]:
        """Mapeo hacia las columnas de `intelligence.product_dnas`."""
        return {
            "summary": self.summary,
            "missing_information": list(self.missing_information),
            "input_kinds": list(self.input_kinds),
        }
