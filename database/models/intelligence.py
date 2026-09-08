"""Esquema `intelligence` — decisiones, evidencia y hallazgos.

`evidence_records` es el contrato central (§17 maestro): toda decisión o
hallazgo apunta ahí. Ninguna afirmación jurídica o de clasificación existe sin
su `EvidenceRecord`.

Las tablas producto de IA heredan `AIDecisionMixin` (`model_*`, `confidence`,
`requires_human_review`). El LLM interpreta y explica; el estado y las reglas
son trazables (§18 maestro).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base
from database.models.enums import (
    ATTRIBUTE_STATUS,
    CLASSIFICATION_STATUS,
    ERROR_TYPE,
    EVIDENCE_KIND,
    FINDING_SEVERITY,
    OPPORTUNITY_STATUS,
    TRADE_FLOW,
)
from database.models.mixins import (
    AIDecisionMixin,
    DataOriginMixin,
    SyntheticMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    ai_call_completeness_check,
    check_enum,
)

_SCHEMA = "intelligence"
_MONEY = sa.Numeric(18, 6)
_CCY = sa.CHAR(3)


class EvidenceRecord(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, Base):
    """Contrato central de evidencia. Toda decisión importante apunta aquí.

    El vínculo con la decisión es blando (`subject_kind` + `subject_id`, sin FK)
    para no crear un ciclo: la decisión referencia su evidencia, no al revés.
    """

    __tablename__ = "evidence_records"
    __table_args__ = (
        sa.Index("ix_evidence_records_subject", "subject_kind", "subject_id"),
        {"schema": _SCHEMA},
    )

    subject_kind: Mapped[str | None] = mapped_column(sa.String(48), nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Fuentes jurídicas que sustentan la decisión.
    source_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=False, server_default="{}"
    )
    legal_rule_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=False, server_default="{}"
    )
    # [{document, article, url, published_at, content_hash}, ...]
    document_refs: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    content_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default="{}"
    )
    engine_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    model_provider: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_by: Mapped[str] = mapped_column(sa.String(16), nullable=False, server_default="engine")
    # Nullable: las filas existentes no lo tienen. created_by (16 chars) no
    # distingue una norma recuperada de un precedente de CBP/EBTI, y esa
    # distinción es la que impide que un caso extranjero se lea como
    # fundamento mexicano (decisión de Persona 1, cambio al Canonical Model).
    evidence_kind: Mapped[str | None] = mapped_column(
        check_enum(EVIDENCE_KIND, "evidence_kind"), nullable=True
    )


class ProductDna(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, AIDecisionMixin, SyntheticMixin, Base
):
    """Representación estructurada de una mercancía (§16 maestro)."""

    __tablename__ = "product_dnas"
    __table_args__ = (
        sa.UniqueConstraint("product_id", "version", name="uq_product_dnas_product_id_version"),
        ai_call_completeness_check(),
        {"schema": _SCHEMA},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("operational.products.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="1")
    is_current: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    input_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(16)), nullable=False, server_default="{}"
    )
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    missing_information: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default="{}"
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.evidence_records.id", ondelete="SET NULL"), nullable=True
    )


class ProductAttribute(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, Base):
    """Un atributo del Product DNA con su propio estado y evidencia (§16 maestro)."""

    __tablename__ = "product_attributes"
    __table_args__ = (
        sa.UniqueConstraint(
            "product_dna_id", "name", name="uq_product_attributes_product_dna_id_name"
        ),
        {"schema": _SCHEMA},
    )

    product_dna_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.product_dnas.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        check_enum(ATTRIBUTE_STATUS, "attribute_status"), nullable=False
    )
    confidence: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 4), nullable=True)
    evidence_reference: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.evidence_records.id", ondelete="SET NULL"), nullable=True
    )


class ClassificationDecision(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, AIDecisionMixin, SyntheticMixin, Base
):
    """Decisión de clasificación. Debe poder responder las 10 preguntas de §49.

    qué -> chapter..nico_code / *_id · por qué -> reasoning · con qué regla ->
    rgi_path + legal_rule_ids · con qué fuente -> evidence_id · qué versión ->
    engine_version + evidence · cuándo vigente -> operation_date · qué dato ->
    product_dna_id + input_snapshot · confianza -> confidence · dinero ->
    estimated_impact_amount · revisión humana -> requires_human_review.
    """

    __tablename__ = "classification_decisions"
    __table_args__ = (
        sa.Index("ix_classification_decisions_product", "product_id", "operation_date"),
        ai_call_completeness_check(),
        {"schema": _SCHEMA},
    )

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.products.id", ondelete="SET NULL"), nullable=True
    )
    product_dna_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.product_dnas.id", ondelete="SET NULL"), nullable=True
    )
    trade_flow: Mapped[str] = mapped_column(check_enum(TRADE_FLOW, "trade_flow"), nullable=False)
    operation_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    status: Mapped[str] = mapped_column(
        check_enum(CLASSIFICATION_STATUS, "classification_status"), nullable=False
    )
    chapter: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    heading: Mapped[str | None] = mapped_column(sa.String(4), nullable=True)
    subheading: Mapped[str | None] = mapped_column(sa.String(6), nullable=True)
    fraction_code: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    nico_code: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    tariff_fraction_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("regulatory.tariff_fractions.id", ondelete="RESTRICT"), nullable=True
    )
    nico_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("regulatory.nicos.id", ondelete="RESTRICT"), nullable=True
    )
    reasoning: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    rgi_path: Mapped[list[str]] = mapped_column(
        ARRAY(sa.String(8)), nullable=False, server_default="{}"
    )
    # Traza completa del RGI: una entrada por paso (rule_id, status,
    # reasoning_summary, candidate_codes, confidence, source_ids,
    # missing_information). Nullable a propósito, SIN default: NULL dice "de
    # esta decisión no conservamos la traza"; un `[]` diría "no hubo pasos",
    # que sería inventar un hecho que no ocurrió. `rgi_path`/`reasoning` ya
    # dicen QUÉ se decidió — esto es lo único que dice CÓMO (Persona 1,
    # 2026-09-08).
    rgi_trace: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    legal_rule_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=False, server_default="{}"
    )
    engine_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.evidence_records.id", ondelete="RESTRICT"), nullable=True
    )
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    missing_information: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default="{}"
    )
    estimated_impact_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    estimated_impact_amount_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)


class ClassificationCandidate(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, Base):
    """Alternativa de clasificación considerada por el RGI Engine."""

    __tablename__ = "classification_candidates"
    __table_args__ = (
        sa.UniqueConstraint(
            "classification_decision_id",
            "rank",
            name="uq_classification_candidates_classification_decision_id_rank",
        ),
        {"schema": _SCHEMA},
    )

    classification_decision_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.classification_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    fraction_code: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    nico_code: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    tariff_fraction_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("regulatory.tariff_fractions.id", ondelete="RESTRICT"), nullable=True
    )
    confidence: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 4), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_selected: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    rejected_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class ShadowReview(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, Base):
    """Una corrida del Pedimento Espejo contra un pedimento (§9.3, §36 maestro).

    Existe porque una auditoría es un evento, no un estado: sin esta fila, la
    API no puede distinguir "no encontré nada" de "no pude revisarlo", y
    `coverage_known` queda forzado a `false` siempre.
    """

    __tablename__ = "shadow_reviews"
    __table_args__ = (
        # La consulta de findings.py: "la revisión más reciente de este pedimento".
        sa.Index("ix_shadow_reviews_pedimento", "pedimento_id", sa.desc("created_at")),
        {"schema": _SCHEMA},
    )

    pedimento_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("operational.pedimentos.id", ondelete="CASCADE"), nullable=False
    )
    # Explícito, no derivado de `unverifiable == '{}'`: ShadowComparison.is_complete.
    is_complete: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    # ShadowComparison.unverifiable tal cual: lista de partidas no comprobadas
    # con su razón. TEXT[], no JSONB — es una lista de cadenas, nada más.
    unverifiable: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default="{}"
    )
    engine_version: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class RiskFinding(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, AIDecisionMixin, SyntheticMixin, Base
):
    """Hallazgo de divergencia entre lo declarado y lo esperado (§21 maestro)."""

    __tablename__ = "risk_findings"
    __table_args__ = (
        sa.Index("ix_risk_findings_severity", "severity"),
        ai_call_completeness_check(),
        {"schema": _SCHEMA},
    )

    pedimento_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.pedimentos.id", ondelete="CASCADE"), nullable=True
    )
    pedimento_item_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.pedimento_items.id", ondelete="CASCADE"), nullable=True
    )
    classification_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.classification_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # A qué corrida del Pedimento Espejo pertenece este hallazgo. Sin esto,
    # dos auditorías del mismo pedimento (antes/después de una rectificación,
    # o tras cargar el Anexo 22) mezclan sus hallazgos y nadie puede decir
    # "en la revisión del 8 de septiembre había estos tres" (Persona 1,
    # 2026-09-08). SET NULL, no CASCADE: si se borra la revisión, el hallazgo
    # sigue siendo un hecho — queda huérfano, no desaparece.
    shadow_review_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.shadow_reviews.id", ondelete="SET NULL"), nullable=True
    )
    finding_type: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    field: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    declared_value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    expected_value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    severity: Mapped[str] = mapped_column(
        check_enum(FINDING_SEVERITY, "finding_severity"), nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    impact_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    impact_amount_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    is_simulation: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.evidence_records.id", ondelete="RESTRICT"), nullable=True
    )


class OpportunityFinding(
    UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, AIDecisionMixin, SyntheticMixin, Base
):
    """Oportunidad de ahorro. `POTENTIAL` nunca se presenta como garantizado (§23)."""

    __tablename__ = "opportunity_findings"
    __table_args__ = (
        ai_call_completeness_check(),
        {"schema": _SCHEMA},
    )

    pedimento_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.pedimentos.id", ondelete="CASCADE"), nullable=True
    )
    pedimento_item_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.pedimento_items.id", ondelete="CASCADE"), nullable=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.products.id", ondelete="SET NULL"), nullable=True
    )
    opportunity_type: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    status: Mapped[str] = mapped_column(
        check_enum(OPPORTUNITY_STATUS, "opportunity_status"),
        nullable=False,
        server_default="POTENTIAL",
    )
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    estimated_saving_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    estimated_saving_amount_currency: Mapped[str | None] = mapped_column(_CCY, nullable=True)
    legal_rule_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=False, server_default="{}"
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey(f"{_SCHEMA}.evidence_records.id", ondelete="RESTRICT"), nullable=True
    )


class GroundTruthRecord(UUIDPrimaryKeyMixin, TimestampMixin, DataOriginMixin, SyntheticMixin, Base):
    """Verdad conocida de una anomalía inyectada, para medir precisión/recall (§26)."""

    __tablename__ = "ground_truth_records"
    __table_args__ = (
        sa.Index("ix_ground_truth_records_error_type", "error_type"),
        {"schema": _SCHEMA},
    )

    pedimento_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.pedimentos.id", ondelete="CASCADE"), nullable=True
    )
    pedimento_item_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("operational.pedimento_items.id", ondelete="CASCADE"), nullable=True
    )
    error_type: Mapped[str] = mapped_column(check_enum(ERROR_TYPE, "error_type"), nullable=False)
    original_value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    mutated_value: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    expected_detection: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true()
    )
    expected_field: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    expected_severity: Mapped[str | None] = mapped_column(
        check_enum(FINDING_SEVERITY, "gt_expected_severity"), nullable=True
    )
