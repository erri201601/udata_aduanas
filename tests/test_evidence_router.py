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


def test_la_vigencia_real_se_contesta_cuando_la_fila_la_trae() -> None:
    """REGRESIÓN REAL (hallazgo de Persona 1): `evidence_records` no tenía
    `valid_from`/`valid_to`, así que esta pregunta salía siempre "UNKNOWN →
    vigente" aunque la norma citada sí tuviera vigencia conocida. Con la
    columna y el mapeo de vuelta (`_a_evidence`), el dossier debe mostrar la
    fecha real, no UNKNOWN."""
    evidencia = _evidencia("LEGAL_SOURCE")
    evidencia.valid_from = date(2022, 6, 7)
    evidencia.valid_to = None

    with _cliente(decision=_decision(), evidencias=[evidencia]) as c:
        cuerpo = c.get(f"/evidence/{DECISION_ID}").json()

    assert "validity" not in cuerpo["unanswered"]
    assert cuerpo["validity"] == ["LIGIE capítulo 84.: 2022-06-07 → vigente"]


def test_con_que_regla_no_se_contesta_con_none() -> None:
    """REGRESIÓN REAL (encontrada en el ensayo de la demo del 29-sep).

    `evidence_records` no tenía columna `rule_id`, así que el motor lo escribía
    en el dominio y se perdía al guardar. La rama «si hay evidencia
    determinista» se cumplía igual y el dossier contestaba «¿con qué regla?»
    con «None (motor 0.1.0)», una vez por paso del RGI — seis veces en la
    decisión que se enseña en la demo.

    Que salga UNKNOWN y en `unanswered` es peor respuesta y mejor dossier: es
    la diferencia entre un hueco que se puede cubrir y uno disfrazado.
    """
    sin_id = _evidencia("DETERMINISTIC")
    sin_id.rule_id = None

    with _cliente(decision=_decision(), evidencias=[sin_id]) as c:
        cuerpo = c.get(f"/evidence/{DECISION_ID}").json()

    assert "None" not in cuerpo["which_rule"]
    assert "which_rule" in cuerpo["unanswered"]
    assert cuerpo["is_complete"] is False


def test_con_que_regla_se_contesta_cuando_la_fila_lo_trae() -> None:
    """La otra mitad: con la columna poblada, la pregunta sí se contesta.

    Sin esta pareja, el arreglo de arriba se podría «pasar» dejando
    `which_rule` siempre sin responder, que era justo lo que no queríamos.
    """
    con_id = _evidencia("DETERMINISTIC")
    con_id.rule_id = "RGI-3c"

    with _cliente(decision=_decision(), evidencias=[con_id]) as c:
        cuerpo = c.get(f"/evidence/{DECISION_ID}").json()

    assert cuerpo["which_rule"] == "RGI-3c (motor 0.1.0)"
    assert "which_rule" not in cuerpo["unanswered"]


def test_el_prompt_del_extractor_no_se_cuela_como_regla() -> None:
    """Un `prompt_id` contesta la pregunta sólo si no hay ninguna regla.

    Listar los dos juntos metería «product_dna/extract v0.1» en la respuesta
    sobre qué regla determinó la fracción, y no la determinó.
    """
    regla = _evidencia("DETERMINISTIC")
    regla.rule_id = "RGI-1"
    modelo = _evidencia("MODEL_OUTPUT")
    modelo.prompt_id = "product_dna/extract"
    modelo.prompt_version = "0.1"

    with _cliente(decision=_decision(), evidencias=[regla, modelo]) as c:
        cuerpo = c.get(f"/evidence/{DECISION_ID}").json()

    assert cuerpo["which_rule"] == "RGI-1 (motor 0.1.0)"
    assert "product_dna/extract" not in cuerpo["which_rule"]


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
