"""Tests del router de clasificaciones.

Lo que se comprueba aquí no es que la API devuelva un código, sino que
devuelva lo necesario para DEFENDERLO: la ruta de reglas, las alternativas
con su motivo de rechazo, y las evidencias con su tipo.

Sin PostgreSQL: la sesión se sustituye con `dependency_overrides`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationCandidate, ClassificationDecision, EvidenceRecord
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
DECISION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
EVIDENCIA_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _aud(fila: Any) -> Any:
    """Rellena lo que en la base pone el servidor y aquí nadie escribe.

    Los `server_default` de SQLAlchemy no se aplican a objetos en memoria: sin
    `flush` las columnas con default siguen en `None` y la validación falla.
    """
    fila.id = fila.id or uuid.uuid4()
    fila.created_at = AHORA
    fila.updated_at = AHORA
    for campo, vacio in (
        ("legal_rule_ids", []),
        ("input_snapshot", {}),
        ("missing_information", []),
        ("rgi_path", []),
        ("source_ids", []),
        ("content_hashes", []),
        ("document_refs", []),
    ):
        if hasattr(fila, campo) and getattr(fila, campo) is None:
            setattr(fila, campo, vacio)
    if hasattr(fila, "requires_human_review") and fila.requires_human_review is None:
        fila.requires_human_review = False
    if hasattr(fila, "is_selected") and fila.is_selected is None:
        fila.is_selected = False
    return fila


def _decision() -> ClassificationDecision:
    d = ClassificationDecision(
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="RESOLVED",
        chapter="84",
        heading="8471",
        subheading="847130",
        fraction_code="84713001",
        reasoning="RGI 1: la partida 8471 comprende máquinas portátiles de tratamiento de datos.",
        rgi_path=["RGI1", "RGI6"],
        engine_version="0.1.0",
        evidence_id=EVIDENCIA_ID,
        missing_information=["voltage_v"],
        confidence=Decimal("0.9100"),
        requires_human_review=True,
        data_origin="SYNTHETIC",
    )
    d.id = DECISION_ID
    return _aud(d)


def _candidatos() -> list[ClassificationCandidate]:
    crudos = [
        (1, "84713001", True, Decimal("0.9100"), None),
        (2, "84714301", False, Decimal("0.4200"), "Es unidad de proceso, no portátil completa."),
        (3, "85176201", False, Decimal("0.1500"), "La función principal no es comunicación."),
    ]
    filas = []
    for rank, codigo, seleccionado, conf, rechazo in crudos:
        c = ClassificationCandidate(
            classification_decision_id=DECISION_ID,
            rank=rank,
            fraction_code=codigo,
            is_selected=seleccionado,
            confidence=conf,
            rejected_reason=rechazo,
            data_origin="SYNTHETIC",
        )
        filas.append(_aud(c))
    return filas


def _evidencias() -> list[EvidenceRecord]:
    legal = EvidenceRecord(
        subject_kind="classification_decision",
        subject_id=DECISION_ID,
        summary="LIGIE capítulo 84: máquinas automáticas para tratamiento de datos.",
        evidence_kind="LEGAL_SOURCE",
        created_by="engine",
        content_hashes=["sha256:demo"],
        data_origin="OFFICIAL",
    )
    legal.id = EVIDENCIA_ID
    modelo = EvidenceRecord(
        subject_kind="classification_decision",
        subject_id=DECISION_ID,
        summary="El modelo dedujo que la función principal es tratamiento de datos.",
        evidence_kind="MODEL_OUTPUT",
        created_by="model",
        model_provider="anthropic",
        model_name="claude-sonnet-5",
        prompt_version="0.1",
        data_origin="SYNTHETIC",
    )
    return [_aud(legal), _aud(modelo)]


class SesionFalsa:
    def __init__(self, *, decision: ClassificationDecision | None) -> None:
        self._decision = decision

    def get(self, _modelo: type, _id: uuid.UUID) -> Any:
        return self._decision

    def scalars(self, sentencia: Any) -> Any:
        entidad = sentencia.column_descriptions[0]["entity"]
        resultado = type("R", (), {})()
        if entidad is ClassificationDecision:
            resultado.all = lambda: [self._decision] if self._decision else []
        elif entidad is ClassificationCandidate:
            resultado.all = lambda: _candidatos() if self._decision else []
        else:
            resultado.all = lambda: _evidencias() if self._decision else []
        return resultado


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(decision=_decision())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cliente_vacio() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(decision=None)
    with TestClient(app) as c:
        yield c


# ── Listado ─────────────────────────────────────────────────────────────────


def test_lista_decisiones(cliente: TestClient) -> None:
    r = cliente.get("/classifications")

    assert r.status_code == 200
    assert r.json()[0]["fraction_code"] == "84713001"


def test_el_limite_esta_acotado(cliente: TestClient) -> None:
    assert cliente.get("/classifications?limit=500").status_code == 422


def test_decision_inexistente_da_404(cliente_vacio: TestClient) -> None:
    assert cliente_vacio.get(f"/classifications/{DECISION_ID}").status_code == 404


# ── Lo que hace defendible una decisión ─────────────────────────────────────


def test_devuelve_la_ruta_de_reglas(cliente: TestClient) -> None:
    """`rgi_path` responde «¿con qué regla?» del §49."""
    assert cliente.get(f"/classifications/{DECISION_ID}").json()["rgi_path"] == [
        "RGI1",
        "RGI6",
    ]


def test_devuelve_las_alternativas_descartadas_con_su_motivo(cliente: TestClient) -> None:
    """Lo más valioso para quien audita: por qué NO fue otra cosa."""
    candidatos = cliente.get(f"/classifications/{DECISION_ID}").json()["candidates"]
    rechazados = [c for c in candidatos if not c["is_selected"]]

    assert len(rechazados) == 2
    assert all(c["rejected_reason"] for c in rechazados)


def test_los_candidatos_llegan_ordenados_por_rango(cliente: TestClient) -> None:
    candidatos = cliente.get(f"/classifications/{DECISION_ID}").json()["candidates"]

    assert [c["rank"] for c in candidatos] == [1, 2, 3]
    assert candidatos[0]["is_selected"] is True


def test_la_evidencia_declara_su_tipo(cliente: TestClient) -> None:
    """Sin `evidence_kind`, la UI no puede distinguir norma de deducción."""
    evidencias = cliente.get(f"/classifications/{DECISION_ID}").json()["evidences"]
    tipos = {e["evidence_kind"] for e in evidencias}

    assert tipos == {"LEGAL_SOURCE", "MODEL_OUTPUT"}


def test_solo_la_fuente_legal_fundamenta(cliente: TestClient) -> None:
    """Dar el mismo peso a la LIGIE y a una deducción arruina el producto."""
    evidencias = cliente.get(f"/classifications/{DECISION_ID}").json()["evidences"]
    fundamentan = [e for e in evidencias if e["evidence_kind"] == "LEGAL_SOURCE"]

    assert len(fundamentan) == 1
    assert fundamentan[0]["data_origin"] == "OFFICIAL"


def test_declara_si_requiere_revision_humana(cliente: TestClient) -> None:
    assert cliente.get(f"/classifications/{DECISION_ID}").json()["requires_human_review"] is True


def test_declara_lo_que_falto(cliente: TestClient) -> None:
    assert cliente.get(f"/classifications/{DECISION_ID}").json()["missing_information"] == [
        "voltage_v"
    ]


def test_avisa_que_la_traza_paso_a_paso_no_esta(cliente: TestClient) -> None:
    """Una explicación parcial presentada como completa es peor que ninguna.

    La base guarda `rgi_path` y un `reasoning` global, pero no el razonamiento
    de cada paso. Mientras eso siga así, la API lo declara y la pantalla lo
    dice, en vez de aparentar una traza que no tiene.
    """
    assert cliente.get(f"/classifications/{DECISION_ID}").json()["trace_available"] is False
