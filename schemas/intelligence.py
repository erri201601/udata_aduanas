"""Contratos del esquema `intelligence` — decisiones, evidencia, hallazgos."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import Field

from schemas.base import (
    AIDecisionFields,
    CanonicalModel,
    DataOriginFields,
    IdentifiedRead,
    SyntheticFields,
)
from schemas.enums import (
    AttributeStatus,
    ClassificationStatus,
    ErrorType,
    EvidenceKind,
    FindingSeverity,
    OpportunityStatus,
    TradeFlow,
)

# ── evidence_records ────────────────────────────────────────────────────────


class EvidenceRecordBase(DataOriginFields):
    subject_kind: str | None = Field(default=None, max_length=48)
    subject_id: uuid.UUID | None = None
    summary: str | None = None
    source_ids: list[uuid.UUID] = Field(default_factory=list)
    legal_rule_ids: list[uuid.UUID] = Field(default_factory=list)
    document_refs: list[dict] = Field(default_factory=list)
    content_hashes: list[str] = Field(default_factory=list)
    engine_version: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    created_by: str = Field(default="engine", max_length=16)
    evidence_kind: EvidenceKind | None = None


class EvidenceRecordCreate(EvidenceRecordBase):
    pass


class EvidenceRecordRead(EvidenceRecordBase, IdentifiedRead):
    pass


class EvidenceRecordUpdate(CanonicalModel):
    summary: str | None = None
    source_ids: list[uuid.UUID] | None = None
    legal_rule_ids: list[uuid.UUID] | None = None
    document_refs: list[dict] | None = None
    content_hashes: list[str] | None = None


# ── product_dnas ────────────────────────────────────────────────────────────


class ProductDnaBase(DataOriginFields, AIDecisionFields, SyntheticFields):
    product_id: uuid.UUID
    version: int = Field(default=1, ge=1)
    is_current: bool = True
    input_kinds: list[str] = Field(default_factory=list)
    summary: str | None = None
    missing_information: list[str] = Field(default_factory=list)
    evidence_id: uuid.UUID | None = None


class ProductDnaCreate(ProductDnaBase):
    pass


class ProductDnaRead(ProductDnaBase, IdentifiedRead):
    pass


class ProductDnaUpdate(CanonicalModel):
    is_current: bool | None = None
    summary: str | None = None
    missing_information: list[str] | None = None
    evidence_id: uuid.UUID | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    requires_human_review: bool | None = None


# ── product_attributes ──────────────────────────────────────────────────────


class ProductAttributeBase(DataOriginFields):
    product_dna_id: uuid.UUID
    name: str = Field(max_length=64)
    value: str | None = None
    unit: str | None = Field(default=None, max_length=16)
    status: AttributeStatus
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    evidence_reference: uuid.UUID | None = None


class ProductAttributeCreate(ProductAttributeBase):
    pass


class ProductAttributeRead(ProductAttributeBase, IdentifiedRead):
    pass


class ProductAttributeUpdate(CanonicalModel):
    value: str | None = None
    unit: str | None = None
    status: AttributeStatus | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    evidence_reference: uuid.UUID | None = None


# ── classification_decisions ────────────────────────────────────────────────


class ClassificationDecisionBase(DataOriginFields, AIDecisionFields, SyntheticFields):
    product_id: uuid.UUID | None = None
    product_dna_id: uuid.UUID | None = None
    reviews_decision_id: uuid.UUID | None = None
    """Qué decisión revisa. Sólo en veredictos HUMAN_VALIDATED."""
    trade_flow: TradeFlow
    operation_date: date
    status: ClassificationStatus
    chapter: str | None = Field(default=None, max_length=2)
    heading: str | None = Field(default=None, max_length=4)
    subheading: str | None = Field(default=None, max_length=6)
    fraction_code: str | None = Field(default=None, max_length=8)
    nico_code: str | None = Field(default=None, max_length=2)
    tariff_fraction_id: uuid.UUID | None = None
    nico_id: uuid.UUID | None = None
    reasoning: str | None = None
    rgi_path: list[str] = Field(default_factory=list)
    # NULL = no se conservó la traza. `[]` significaría "no hubo pasos".
    rgi_trace: list[dict] | None = None
    legal_rule_ids: list[uuid.UUID] = Field(default_factory=list)
    engine_version: str | None = None
    evidence_id: uuid.UUID | None = None
    input_snapshot: dict = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    estimated_impact_amount: Decimal | None = None
    estimated_impact_amount_currency: str | None = None


class ClassificationDecisionCreate(ClassificationDecisionBase):
    pass


class ClassificationDecisionRead(ClassificationDecisionBase, IdentifiedRead):
    pass


class ClassificationDecisionUpdate(CanonicalModel):
    status: ClassificationStatus | None = None
    chapter: str | None = None
    heading: str | None = None
    subheading: str | None = None
    fraction_code: str | None = None
    nico_code: str | None = None
    tariff_fraction_id: uuid.UUID | None = None
    nico_id: uuid.UUID | None = None
    reasoning: str | None = None
    rgi_path: list[str] | None = None
    legal_rule_ids: list[uuid.UUID] | None = None
    evidence_id: uuid.UUID | None = None
    missing_information: list[str] | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    requires_human_review: bool | None = None


# ── classification_candidates ───────────────────────────────────────────────


class ClassificationCandidateBase(DataOriginFields):
    classification_decision_id: uuid.UUID
    rank: int = Field(ge=1)
    fraction_code: str | None = Field(default=None, max_length=8)
    nico_code: str | None = Field(default=None, max_length=2)
    tariff_fraction_id: uuid.UUID | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    reasoning: str | None = None
    is_selected: bool = False
    rejected_reason: str | None = None


class ClassificationCandidateCreate(ClassificationCandidateBase):
    pass


class ClassificationCandidateRead(ClassificationCandidateBase, IdentifiedRead):
    pass


class ClassificationCandidateUpdate(CanonicalModel):
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    reasoning: str | None = None
    is_selected: bool | None = None
    rejected_reason: str | None = None


# ── shadow_reviews ──────────────────────────────────────────────────────────


class ShadowReviewBase(DataOriginFields):
    pedimento_id: uuid.UUID
    is_complete: bool
    # ShadowComparison.unverifiable tal cual: lista de razones, no JSONB.
    unverifiable: list[str] = Field(default_factory=list)
    engine_version: str | None = None


class ShadowReviewCreate(ShadowReviewBase):
    pass


class ShadowReviewRead(ShadowReviewBase, IdentifiedRead):
    pass


class ShadowReviewUpdate(CanonicalModel):
    is_complete: bool | None = None
    unverifiable: list[str] | None = None


# ── risk_findings ───────────────────────────────────────────────────────────


class RiskFindingBase(DataOriginFields, AIDecisionFields, SyntheticFields):
    pedimento_id: uuid.UUID | None = None
    pedimento_item_id: uuid.UUID | None = None
    classification_decision_id: uuid.UUID | None = None
    # A qué corrida del Pedimento Espejo pertenece este hallazgo.
    shadow_review_id: uuid.UUID | None = None
    finding_type: str = Field(max_length=48)
    field: str | None = Field(default=None, max_length=64)
    declared_value: str | None = None
    expected_value: str | None = None
    severity: FindingSeverity
    rationale: str | None = None
    impact_amount: Decimal | None = None
    impact_amount_currency: str | None = None
    is_simulation: bool = False
    evidence_id: uuid.UUID | None = None


class RiskFindingCreate(RiskFindingBase):
    pass


class RiskFindingRead(RiskFindingBase, IdentifiedRead):
    pass


class RiskFindingUpdate(CanonicalModel):
    severity: FindingSeverity | None = None
    rationale: str | None = None
    expected_value: str | None = None
    impact_amount: Decimal | None = None
    evidence_id: uuid.UUID | None = None
    requires_human_review: bool | None = None


# ── opportunity_findings ────────────────────────────────────────────────────


class OpportunityFindingBase(DataOriginFields, AIDecisionFields, SyntheticFields):
    pedimento_id: uuid.UUID | None = None
    pedimento_item_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    opportunity_type: str = Field(max_length=48)
    status: OpportunityStatus = OpportunityStatus.POTENTIAL
    rationale: str | None = None
    estimated_saving_amount: Decimal | None = None
    estimated_saving_amount_currency: str | None = None
    # §23: un ahorro POTENTIAL ya se presenta como potencial. Esto dice algo
    # distinto y que faltaba — si sale de una operación inventada. Un ahorro
    # simulado sin esta marca es la regla 4 al revés: SYNTHETIC presentado
    # como real, y en el campo que alguien querría cobrar.
    is_simulation: bool = False
    legal_rule_ids: list[uuid.UUID] = Field(default_factory=list)
    evidence_id: uuid.UUID | None = None


class OpportunityFindingCreate(OpportunityFindingBase):
    pass


class OpportunityFindingRead(OpportunityFindingBase, IdentifiedRead):
    pass


class OpportunityFindingUpdate(CanonicalModel):
    # POTENTIAL nunca se presenta como ahorro garantizado (§23 maestro).
    status: OpportunityStatus | None = None
    rationale: str | None = None
    estimated_saving_amount: Decimal | None = None
    legal_rule_ids: list[uuid.UUID] | None = None
    evidence_id: uuid.UUID | None = None
    requires_human_review: bool | None = None


# ── ground_truth_records ────────────────────────────────────────────────────


class GroundTruthRecordBase(DataOriginFields, SyntheticFields):
    pedimento_id: uuid.UUID | None = None
    pedimento_item_id: uuid.UUID | None = None
    error_type: ErrorType
    original_value: str | None = None
    mutated_value: str | None = None
    expected_detection: bool = True
    expected_field: str | None = Field(default=None, max_length=64)
    expected_severity: FindingSeverity | None = None


class GroundTruthRecordCreate(GroundTruthRecordBase):
    pass


class GroundTruthRecordRead(GroundTruthRecordBase, IdentifiedRead):
    pass


class GroundTruthRecordUpdate(CanonicalModel):
    original_value: str | None = None
    mutated_value: str | None = None
    expected_detection: bool | None = None
    expected_field: str | None = None
    expected_severity: FindingSeverity | None = None
