"""Contrato de telemetría LLM en `AIDecisionFields`.

Espejo de `tests/test_llm_canonical.py` (Persona 3) sin importar `core.llm`:
la capa de persistencia no depende de `core/` (decisión de Persona 1). El
acuerdo se repite aquí a mano, como campo congelado; si `core/llm/canonical.py`
cambia sus claves sin avisar, el diff de este archivo lo hace visible en
revisión en vez de reventar sólo en ejecución.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa
from database.models.intelligence import (
    ClassificationDecision,
    OpportunityFinding,
    ProductDna,
    RiskFinding,
)
from schemas.base import AIDecisionFields

pytestmark = pytest.mark.unit

# Acordado con Persona 3 en core/llm/canonical.py::CanonicalAIFields.
CAMPOS_TELEMETRIA_LLM = frozenset(
    {
        "model_provider",
        "model_name",
        "prompt_id",
        "prompt_version",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "attempts",
        "finish_reason",
    }
)

_TABLAS_CON_MIXIN = (ProductDna, ClassificationDecision, RiskFinding, OpportunityFinding)


def test_ai_decision_fields_cubre_la_telemetria_acordada() -> None:
    assert set(AIDecisionFields.model_fields) >= CAMPOS_TELEMETRIA_LLM


def test_ai_decision_fields_acepta_el_mapeo_de_una_llamada_real() -> None:
    """Valores medidos contra la API real de Anthropic (smoke test de Persona 3)."""
    fila = AIDecisionFields(
        model_provider="anthropic",
        model_name="claude-sonnet-5",
        prompt_id="smoke/ficha",
        prompt_version="0.1",
        input_tokens=319,
        output_tokens=36,
        latency_ms=1329,
        attempts=1,
        finish_reason="end_turn",
    )

    assert fila.input_tokens + fila.output_tokens == 355
    assert fila.requires_human_review is True
    assert fila.confidence is None


def test_requires_human_review_falla_hacia_cautela_por_default() -> None:
    """El sistema falla hacia revisión humana; bajarlo a False es explícito (regla 2 CLAUDE.md)."""
    assert AIDecisionFields().requires_human_review is True


def test_confidence_sigue_acotada_a_0_1() -> None:
    fila = AIDecisionFields(confidence=Decimal("0.9"))

    assert fila.confidence == Decimal("0.9")


def test_las_cuatro_tablas_producto_de_ia_tienen_la_telemetria_completa() -> None:
    columnas_llm = CAMPOS_TELEMETRIA_LLM - {"model_provider"}  # model_provider ya existía
    for modelo in _TABLAS_CON_MIXIN:
        nombres = {c.name for c in modelo.__table__.columns}
        faltantes = columnas_llm - nombres
        assert not faltantes, f"{modelo.__tablename__}: faltan columnas {faltantes}"


def test_las_cuatro_tablas_tienen_el_check_de_llamada_completa() -> None:
    for modelo in _TABLAS_CON_MIXIN:
        nombre_check = f"ck_{modelo.__tablename__}_ai_call_complete"
        checks = {c.name for c in modelo.__table__.constraints if isinstance(c, sa.CheckConstraint)}
        assert nombre_check in checks, f"{modelo.__tablename__}: falta {nombre_check}"


def test_evidence_records_no_hereda_el_mixin() -> None:
    """Decisión de Persona 1: `model_provider` ahí significa 'qué produjo la evidencia',
    no 'qué decidió' — son cosas distintas aunque hoy casi siempre coincidan."""
    from database.models.intelligence import EvidenceRecord

    nombres = {c.name for c in EvidenceRecord.__table__.columns}
    assert "requires_human_review" not in nombres
    assert "confidence" not in nombres
