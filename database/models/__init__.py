"""Modelos SQLAlchemy del Canonical Data Model.

Alembic importa este paquete para descubrir metadata. Cada modelo nuevo debe
importarse aquí, o su tabla no aparecerá en las migraciones autogeneradas.

28 entidades en 3 esquemas (§8 Persona 1 / §4 TAREA_P2):
  regulatory   — dato normativo real (OFFICIAL/PUBLIC/LICENSED)
  operational  — clientes, proveedores, operaciones (hoy SYNTHETIC)
  intelligence — decisiones, evidencia, hallazgos
"""

from database.models.base import Base
from database.models.intelligence import (
    ClassificationCandidate,
    ClassificationDecision,
    EvidenceRecord,
    GroundTruthRecord,
    OpportunityFinding,
    ProductAttribute,
    ProductDna,
    RiskFinding,
    ShadowReview,
)
from database.models.operational import (
    Client,
    Cove,
    Invoice,
    InvoiceItem,
    Pedimento,
    PedimentoItem,
    Product,
    Supplier,
    SyntheticScenario,
)
from database.models.regulatory import (
    CustomsOffice,
    LegalChunkRecord,
    LegalDocument,
    LegalRule,
    LegalSource,
    Nico,
    NomenclatureSynonym,
    NonTariffRegulation,
    PedimentoClave,
    PedimentoIdentifier,
    RegulatoryEvent,
    TariffFraction,
    TariffHeading,
    TariffHeadingGroup,
    UnitOfMeasure,
)

__all__ = [
    "Base",
    "ClassificationCandidate",
    "ClassificationDecision",
    "Client",
    "Cove",
    "CustomsOffice",
    "EvidenceRecord",
    "GroundTruthRecord",
    "Invoice",
    "InvoiceItem",
    "LegalChunkRecord",
    "LegalDocument",
    "LegalRule",
    "LegalSource",
    "Nico",
    "NomenclatureSynonym",
    "NonTariffRegulation",
    "OpportunityFinding",
    "Pedimento",
    "PedimentoClave",
    "PedimentoIdentifier",
    "PedimentoItem",
    "Product",
    "ProductAttribute",
    "ProductDna",
    "RegulatoryEvent",
    "RiskFinding",
    "ShadowReview",
    "Supplier",
    "SyntheticScenario",
    "TariffFraction",
    "TariffHeading",
    "TariffHeadingGroup",
    "UnitOfMeasure",
]
