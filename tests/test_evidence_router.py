"""Tests del dossier §49.

El que importa es `test_muestra_lo_no_respondido`: un dossier incompleto
pintado como completo miente, y esta es la pantalla que se enseña cuando
alguien audita una decisión.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationDecision, EvidenceRecord
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
DECISION_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


def _aud(fila: Any) -> Any:
    fila.id = fila.id or uuid.uuid4()
    fila.created_at = AHORA
    fila.updated_at = AHORA
    for campo, vacio in (
        ("legal_rule_ids", []),
        ("input_snapshot", {"weight_kg": "1.4"}),
        ("missing_information", []),
        ("rgi_path", []),
        ("source_ids", []),
        ("content_hashes", []),
        ("document_refs", []),
    ):
        if hasattr(fila, campo) and getattr(fila, campo) is None:
            setattr(fila, campo, vacio)
    if getattr(fila, "requires_human_review", None) is None:
        fila.requires_human_review = False
    return fila


def _decision() -> ClassificationDecision:
    d = ClassificationDecision(
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="RESOLVED",
        fraction_code="84713001",
        reasoning="RGI 1: la partida 8471 comprende máquinas portátiles.",
        rgi_path=["RGI1"],
        engine_version="0.1.0",
        confidence=Decimal("0.9100"),
        requires_human_review=True,
        data_origin="SYNTHETIC",
    )
    d.id = DECISION_ID
    return _aud(d)


def _evidencia(kind: str | None) -> EvidenceRecord:
    e = EvidenceRecord(
        subject_kind="classification_decision",
        subject_id=DECISION_ID,
        summary="LIGIE capítulo 84.",
        evidence_kind=kind,
        created_by="engine",
        engine_version="0.1.0",
        data_origin="OFFICIAL",
    )
    return _aud(e)


class SesionFalsa:
    def __init__(self, *, decision: Any, evidencias: list[EvidenceRecord]) -> None:
        self._decision = decision
        self._evidencias = evidencias

    def get(self, _modelo: type, _id: uuid.UUID) -> Any:
        return self._decision

    def scalars(self, _sentencia: Any) -> Any:
        r = type("R", (), {})()
        r.all = lambda: self._evidencias
        return r


def _cliente(*, decision: Any, evidencias: list[EvidenceRecord]) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(
        decision=decision, evidencias=evidencias
    )
    return TestClient(app)


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    with _cliente(decision=_decision(), evidencias=[_evidencia("LEGAL_SOURCE")]) as c:
        yield c


# ── Lo que no se pudo responder ─────────────────────────────────────────────


def test_muestra_lo_no_respondido(cliente: TestClient) -> None:
    """EL TEST QUE IMPORTA.

    Un dossier incompleto pintado como completo miente, y ésta es la pantalla
    que se enseña cuando alguien audita una decisión.
    """
    cuerpo = cliente.get(f"/evidence/{DECISION_ID}").json()

    assert "unanswered" in cuerpo
    assert isinstance(cuerpo["unanswered"], list)
    # Con una sola evidencia sin documento ni vigencia, no están las diez.
    assert cuerpo["is_complete"] is False
    assert cuerpo["unanswered"]


def test_is_complete_no_se_deriva_de_una_lista_vacia(cliente: TestClient) -> None:
    """Coherencia: si hay preguntas sin responder, no está completo."""
    cuerpo = cliente.get(f"/evidence/{DECISION_ID}").json()

    assert cuerpo["is_complete"] == (not cuerpo["unanswered"])


def test_responde_las_preguntas_que_si_puede(cliente: TestClient) -> None:
    """Un hueco en algunas no borra las que sí se contestan."""
    cuerpo = cliente.get(f"/evidence/{DECISION_ID}").json()

    assert cuerpo["what"]
    assert cuerpo["which_rule"]
    assert cuerpo["requires_human_review"] is True


# ── Evidencias que no se pueden interpretar ─────────────────────────────────


def test_una_evidencia_sin_tipo_no_entra_al_dossier() -> None:
    """Suponerle un tipo sería inventar la procedencia de un dato."""
    with _cliente(decision=_decision(), evidencias=[_evidencia(None)]) as c:
        cuerpo = c.get(f"/evidence/{DECISION_ID}").json()

    assert cuerpo["uninterpretable_evidences"] == 1
    assert cuerpo["is_complete"] is False


def test_las_inservibles_se_cuentan_no_se_ocultan() -> None:
    """Si el dossier tiene huecos, hay que poder saber si la causa es ésta."""
    evidencias = [_evidencia("LEGAL_SOURCE"), _evidencia(None), _evidencia(None)]
    with _cliente(decision=_decision(), evidencias=evidencias) as c:
        cuerpo = c.get(f"/evidence/{DECISION_ID}").json()

    assert cuerpo["uninterpretable_evidences"] == 2


def test_sin_evidencias_el_dossier_no_finge(cliente: TestClient) -> None:
    """Cero evidencias no produce un dossier completo."""
    with _cliente(decision=_decision(), evidencias=[]) as c:
        cuerpo = c.get(f"/evidence/{DECISION_ID}").json()

    assert cuerpo["is_complete"] is False
    assert cuerpo["unanswered"]


def test_decision_inexistente_da_404() -> None:
    with _cliente(decision=None, evidencias=[]) as c:
        assert c.get(f"/evidence/{DECISION_ID}").status_code == 404


def test_el_dossier_no_reejecuta_el_motor(cliente: TestClient) -> None:
    """Se ensambla desde evidencias ya escritas, no reclasificando.

    Reclasificar para explicar una decisión pasada mostraría un razonamiento
    distinto al que se firmó si la tarifa cambió.
    """
    primero = cliente.get(f"/evidence/{DECISION_ID}").json()
    segundo = cliente.get(f"/evidence/{DECISION_ID}").json()

    assert primero["what"] == segundo["what"]
    assert primero["unanswered"] == segundo["unanswered"]
