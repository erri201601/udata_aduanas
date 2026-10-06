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
from types import SimpleNamespace
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


TRAZA = [
    {
        "rule_id": "RGI-1",
        "status": "RESOLVED",
        "reasoning_summary": "La partida 8471 comprende máquinas de tratamiento de datos.",
        "candidate_codes": ["8471"],
        "confidence": "0.9100",
        "source_ids": [],
        "missing_information": [],
        "preguntas": [],
        "descartadas": [],
    },
    {
        "rule_id": "RGI-6",
        "status": "RESOLVED",
        "reasoning_summary": "Entre subpartidas, la 8471.30 es la de portátiles.",
        "candidate_codes": ["84713001"],
        "confidence": "0.9100",
        "source_ids": [],
        "missing_information": [],
        "preguntas": [],
        "descartadas": [],
    },
]


def _decision(*, con_traza: bool = True) -> ClassificationDecision:
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
    # NULL = no se conservó la traza. Distinto de [] = no hubo pasos.
    d.rgi_trace = TRAZA if con_traza else None
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

    #: El veredicto humano que devuelve `.first()`. `None` = nadie revisó.
    _veredicto: Any = None

    #: ¿Existe en la tarifa la fracción del veredicto? Por defecto sí, para que
    #: los tests que no hablan del catálogo sigan probando lo suyo.
    _fraccion_en_catalogo: bool = True

    #: ¿Hay tarifa cargada? Con `False` la pregunta no se puede contestar, y
    #: `en_catalogo` debe salir `None` en vez de `False`.
    _hay_tarifa: bool = True

    def scalar(self, sentencia: Any) -> Any:
        # «¿hay tarifa?» no filtra por código; «¿existe ESTE código?» sí.
        if "tariff_fractions.code =" in str(sentencia):
            return uuid.uuid4() if self._fraccion_en_catalogo else None
        return uuid.uuid4() if self._hay_tarifa else None

    def scalars(self, sentencia: Any) -> Any:
        entidad = sentencia.column_descriptions[0]["entity"]
        resultado = type("R", (), {})()
        if entidad is ClassificationDecision:
            resultado.all = lambda: [self._decision] if self._decision else []
            # La búsqueda del dictamen humano: `.first()`, y `None` porque en
            # estos tests nadie ha revisado la decisión todavía.
            resultado.first = lambda: self._veredicto
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


def test_la_traza_llega_paso_a_paso(cliente: TestClient) -> None:
    """Cada paso con su razonamiento: es lo que hace defendible la decisión."""
    cuerpo = cliente.get(f"/classifications/{DECISION_ID}").json()

    assert cuerpo["trace_available"] is True
    assert [p["rule_id"] for p in cuerpo["rgi_trace"]] == ["RGI-1", "RGI-6"]
    assert all(p["reasoning_summary"] for p in cuerpo["rgi_trace"])


def test_sin_traza_conservada_se_declara() -> None:
    """`NULL` significa «no la conservamos», no «no hubo pasos».

    Las decisiones anteriores a la columna llegan así. Taparlo con un `[]`
    haría creer que el motor no evaluó ninguna regla.
    """
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(decision=_decision(con_traza=False))
    with TestClient(app) as c:
        cuerpo = c.get(f"/classifications/{DECISION_ID}").json()

    assert cuerpo["trace_available"] is False
    assert cuerpo["rgi_trace"] is None


def test_la_traza_del_test_coincide_con_la_que_escribe_el_repositorio() -> None:
    """El fixture no puede inventarse la forma de la traza.

    Si `database.repositories.classification._traza()` cambia sus claves, este
    test falla antes de que la pantalla empiece a leer campos que ya no
    existen. Es la única forma de que un fixture siga siendo una prueba y no
    una suposición.
    """
    from datetime import date

    from core.classification.result import ClassificationOutcome
    from core.rgi_engine.context import TariffCandidate
    from core.rgi_engine.results import ClassificationTrace, RGIResult, RGIStatus
    from database.repositories.classification import _traza

    paso = RGIResult(
        rule_id="RGI-1",
        status=RGIStatus.RESOLVED,
        reasoning_summary="La partida 8471 comprende máquinas de tratamiento de datos.",
        candidate_codes=(
            TariffCandidate(code="8471", text="máquinas automáticas", level="heading"),
        ),
        confidence=Decimal("0.91"),
    )
    outcome = ClassificationOutcome(
        trace=ClassificationTrace(
            steps=(paso,), final_status=RGIStatus.RESOLVED, resolved_code="84713001"
        ),
        operation_date=date(2026, 3, 15),
    )

    assert sorted(_traza(outcome)[0]) == sorted(TRAZA[0])


# ── La decisión enseña su dictamen (Persona 1, 29-sep) ─────────────────────


def test_una_decision_ya_dictaminada_lo_dice() -> None:
    """La pantalla decía «requiere que una persona lo revise» sobre un caso
    que una persona YA había revisado.

    El trabajo del clasificador quedaba invisible justo donde más falta hace:
    al lado de lo que la máquina no pudo.
    """
    from datetime import UTC, datetime

    veredicto = SimpleNamespace(
        id=uuid.uuid4(),
        fraction_code="73053199",
        reasoning="Revisión humana de CESAR: corrige.",
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
        # La comprobación contra el catálogo va con la fecha DE LA OPERACIÓN,
        # no con hoy: una fracción derogada existió de verdad (regla 5).
        operation_date=date(2026, 8, 3),
    )
    sesion = SesionFalsa(decision=_decision())
    sesion._veredicto = veredicto
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        cuerpo = c.get(f"/classifications/{DECISION_ID}").json()

    assert cuerpo["dictamen"] is not None
    assert cuerpo["dictamen"]["fraction_code"] == "73053199"
    assert "CESAR" in cuerpo["dictamen"]["reasoning"]


def test_un_dictamen_con_fraccion_fuera_de_catalogo_lo_declara() -> None:
    """REGRESIÓN REAL (ensayo de la demo del 29-sep).

    `73239399` sobre un sartén de acero inoxidable: bajo esa subpartida sólo
    existe `73239305`. Entró antes de que hubiera guardarraíl, así que el
    guardarraíl del endpoint de revisión no la arregla — y la pantalla la
    pintaba en verde como «la única verdad del sistema que no generamos
    nosotros», con el respaldo visual de la tarifa y sin la tarifa detrás.

    Se comprueba al LEER precisamente por eso: por las filas que ya están.
    """
    from datetime import UTC, datetime

    veredicto = SimpleNamespace(
        id=uuid.uuid4(),
        fraction_code="73239399",
        reasoning="Revisión humana de CESAR: corrige.",
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
        operation_date=date(2026, 8, 3),
    )
    sesion = SesionFalsa(decision=_decision())
    sesion._veredicto = veredicto
    sesion._fraccion_en_catalogo = False
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        cuerpo = c.get(f"/classifications/{DECISION_ID}").json()

    assert cuerpo["dictamen"]["en_catalogo"] is False
    # Y el dictamen NO desaparece: el criterio de la persona sigue ahí.
    assert cuerpo["dictamen"]["fraction_code"] == "73239399"


def test_un_dictamen_sin_fraccion_no_se_comprueba_contra_el_catalogo() -> None:
    """`en_catalogo` es `None`, no `False`.

    Coincidir en que no se puede determinar no tiene nada que comprobar, y
    marcarlo como fuera de catálogo lo leería como un error del revisor.
    """
    from datetime import UTC, datetime

    veredicto = SimpleNamespace(
        id=uuid.uuid4(),
        fraction_code=None,
        reasoning="Revisión humana de CESAR: confirma que no se puede determinar.",
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
        operation_date=date(2026, 8, 3),
    )
    sesion = SesionFalsa(decision=_decision())
    sesion._veredicto = veredicto
    sesion._fraccion_en_catalogo = False
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        cuerpo = c.get(f"/classifications/{DECISION_ID}").json()

    assert cuerpo["dictamen"]["en_catalogo"] is None


def test_sin_tarifa_cargada_en_catalogo_es_nulo_y_no_falso() -> None:
    """`None` es «no consta»; `False` es «comprobado y no está».

    Con la tarifa sin cargar, decir `False` acusaría al revisor de un error que
    sólo demuestra que nos falta el catálogo, y la pantalla pintaría el aviso
    ámbar sobre un dictamen correcto.
    """
    from datetime import UTC, datetime

    veredicto = SimpleNamespace(
        id=uuid.uuid4(),
        fraction_code="73239305",
        reasoning="Revisión humana de CESAR: corrige.",
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
        operation_date=date(2026, 8, 3),
    )
    sesion = SesionFalsa(decision=_decision())
    sesion._veredicto = veredicto
    sesion._hay_tarifa = False
    sesion._fraccion_en_catalogo = False
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        cuerpo = c.get(f"/classifications/{DECISION_ID}").json()

    assert cuerpo["dictamen"]["en_catalogo"] is None


def test_sin_dictamen_el_campo_es_nulo_y_no_un_dictamen_vacio() -> None:
    """`None` es «nadie se ha pronunciado». Un dictamen sin fracción es «una
    persona miró y tampoco pudo determinarla». No son lo mismo."""
    sesion = SesionFalsa(decision=_decision())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        cuerpo = c.get(f"/classifications/{DECISION_ID}").json()

    assert cuerpo["dictamen"] is None
