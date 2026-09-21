"""Enumerados del contrato — espejo de `database/models/enums.py`.

Se declaran como `StrEnum` para que serialicen a su valor de texto y validen
exactamente los mismos vocabularios cerrados que el `CHECK` de la base.
"""

from __future__ import annotations

from enum import StrEnum


class DataOrigin(StrEnum):
    """§9 maestro — los cinco orígenes de dato. Cerrado."""

    OFFICIAL = "OFFICIAL"
    PUBLIC = "PUBLIC"
    LICENSED = "LICENSED"
    SYNTHETIC = "SYNTHETIC"
    HUMAN_VALIDATED = "HUMAN_VALIDATED"


class SourceKind(StrEnum):
    """Origen de una fuente registrada: nunca es sintética."""

    OFFICIAL = "OFFICIAL"
    PUBLIC = "PUBLIC"
    LICENSED = "LICENSED"


class AttributeStatus(StrEnum):
    """§16 maestro — estado de un atributo de Product DNA."""

    OBSERVED = "OBSERVED"
    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    MISSING = "MISSING"


class TradeFlow(StrEnum):
    """Sentido de la operación."""

    IMPORT = "IMPORT"
    EXPORT = "EXPORT"


class ClassificationStatus(StrEnum):
    """§18 maestro — cómo termina una evaluación de clasificación."""

    RESOLVED = "RESOLVED"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class FindingSeverity(StrEnum):
    """§21 maestro — severidad de un hallazgo."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class OpportunityStatus(StrEnum):
    """§23 maestro — ciclo de vida de una oportunidad."""

    POTENTIAL = "POTENTIAL"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ErrorType(StrEnum):
    """§25 maestro — catálogo inicial de errores inyectables."""

    WRONG_FRACTION = "WRONG_FRACTION"
    WRONG_NICO = "WRONG_NICO"
    WRONG_ORIGIN = "WRONG_ORIGIN"
    MISSING_NOM = "MISSING_NOM"
    MISSED_PROSEC = "MISSED_PROSEC"
    MISSED_PREFERENCE = "MISSED_PREFERENCE"
    WRONG_VALUE = "WRONG_VALUE"
    MISSING_INCREMENTABLE = "MISSING_INCREMENTABLE"
    WRONG_IDENTIFIER = "WRONG_IDENTIFIER"
    INCONSISTENT_SKU_CLASSIFICATION = "INCONSISTENT_SKU_CLASSIFICATION"

    # Ampliación aprobada por Persona 1 el 21-sep-2026, al validar el corpus
    # espejo V1. El §25 dice «implementar inicialmente», no «sólo estos».
    # Los tres son cosas que los diez originales no sabían nombrar: una clave
    # de unidad inexistente, una cantidad incoherente y una ficha técnica sin
    # la característica que permite clasificar.
    WRONG_UNIT = "WRONG_UNIT"
    INCONSISTENT_QUANTITY = "INCONSISTENT_QUANTITY"
    MISSING_TECHNICAL_FIELD = "MISSING_TECHNICAL_FIELD"


class LegalDocumentKind(StrEnum):
    """Tipo de documento jurídico normalizado."""

    LAW = "LAW"
    REGULATION = "REGULATION"
    RULE = "RULE"
    ANNEX = "ANNEX"
    TARIFF = "TARIFF"
    DECREE = "DECREE"
    NOM = "NOM"
    TREATY = "TREATY"
    OTHER = "OTHER"


class RegulatoryEventKind(StrEnum):
    """Naturaleza de un evento del DOF Regulatory Watcher."""

    PUBLICATION = "PUBLICATION"
    AMENDMENT = "AMENDMENT"
    REPEAL = "REPEAL"
    ERRATA = "ERRATA"
    NOTICE = "NOTICE"


class EvidenceKind(StrEnum):
    """Tipo de evidencia en evidence_records. Espejo de core.evidence.kinds.EvidenceKind."""

    LEGAL_SOURCE = "LEGAL_SOURCE"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    DETERMINISTIC = "DETERMINISTIC"
    HUMAN = "HUMAN"
    COMPARABLE = "COMPARABLE"
