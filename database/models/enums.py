"""Vocabularios cerrados del Canonical Data Model.

Cada tupla alimenta un `sa.Enum(..., native_enum=False, create_constraint=True)`
— es decir `VARCHAR` + `CHECK`, nunca un tipo `ENUM` nativo de PostgreSQL
(§2 TAREA_P2). Añadir un valor es un cambio de contrato: lo aprueba Persona 1
(§9 maestro).

Los mismos valores se exponen a Pydantic en `schemas/enums.py`; esta es la
fuente de verdad para la capa de base de datos.
"""

from __future__ import annotations

from typing import Final

# §9 maestro — los cinco orígenes de dato. Cerrado. No se inventa un sexto.
DATA_ORIGIN: Final = (
    "OFFICIAL",
    "PUBLIC",
    "LICENSED",
    "SYNTHETIC",
    "HUMAN_VALIDATED",
)

# Origen de una fuente registrada (`legal_sources`): nunca es sintética.
SOURCE_KIND: Final = ("OFFICIAL", "PUBLIC", "LICENSED")

# §16 maestro — estado de cada atributo de Product DNA.
ATTRIBUTE_STATUS: Final = ("OBSERVED", "EXTRACTED", "INFERRED", "MISSING")

# Sentido de la operación de comercio exterior.
TRADE_FLOW: Final = ("IMPORT", "EXPORT")

# §18 maestro — estado con el que termina una evaluación de clasificación.
CLASSIFICATION_STATUS: Final = (
    "RESOLVED",
    "INSUFFICIENT_INFORMATION",
    "HUMAN_REVIEW_REQUIRED",
)

# §21 maestro — severidad de un hallazgo de auditoría/riesgo.
FINDING_SEVERITY: Final = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")

# §23 maestro — ciclo de vida de una oportunidad. POTENTIAL != ahorro garantizado.
OPPORTUNITY_STATUS: Final = ("POTENTIAL", "VALIDATED", "REJECTED")

# §25 maestro — catálogo inicial de errores inyectables para Ground Truth.
ERROR_TYPE: Final = (
    "WRONG_FRACTION",
    "WRONG_NICO",
    "WRONG_ORIGIN",
    "MISSING_NOM",
    "MISSED_PROSEC",
    "MISSED_PREFERENCE",
    "WRONG_VALUE",
    "MISSING_INCREMENTABLE",
    "WRONG_IDENTIFIER",
    "INCONSISTENT_SKU_CLASSIFICATION",
)

# Tipo de documento jurídico normalizado.
LEGAL_DOCUMENT_KIND: Final = (
    "LAW",
    "REGULATION",
    "RULE",
    "ANNEX",
    "TARIFF",
    "DECREE",
    "NOM",
    "TREATY",
    "OTHER",
)

# Naturaleza de un evento del DOF Regulatory Watcher.
REGULATORY_EVENT_KIND: Final = (
    "PUBLICATION",
    "AMENDMENT",
    "REPEAL",
    "ERRATA",
    "NOTICE",
)

# Tipo de evidencia en evidence_records. Espejo de core.evidence.kinds.EvidenceKind
# (Evidence Contract) — created_by (16 chars) no distingue una norma recuperada
# de un precedente extranjero, y esa distinción es la que impide que un caso
# de CBP/EBTI se lea como fundamento jurídico mexicano. Aprobado por Persona 1.
EVIDENCE_KIND: Final = (
    "LEGAL_SOURCE",
    "MODEL_OUTPUT",
    "DETERMINISTIC",
    "HUMAN",
    "COMPARABLE",
)
