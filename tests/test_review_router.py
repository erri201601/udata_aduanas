"""Tests de la bandeja de revisión humana.

El que importa es `test_la_correccion_no_borra_la_respuesta_de_la_maquina`:
medir «fraction accuracy» del §39 exige conservar las dos respuestas. Si la
revisión editara la decisión original, el numerador de esa métrica
desaparecería y con él la única forma de saber si el sistema mejora.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationDecision, Product
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
DECISION_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")


def _aud(fila: Any) -> Any:
    fila.id = fila.id or uuid.uuid4()
    fila.created_at = AHORA
    fila.updated_at = AHORA
    for campo, vacio in (
        ("legal_rule_ids", []),
        ("input_snapshot", {}),
        ("missing_information", []),
        ("rgi_path", ["RGI1"]),
    ):
        if hasattr(fila, campo) and getattr(fila, campo) is None:
            setattr(fila, campo, vacio)
    return fila


def _decision(*, origen: str = "SYNTHETIC", pendiente: bool = True) -> ClassificationDecision:
    d = ClassificationDecision(
        product_id=uuid.uuid4(),
        product_dna_id=uuid.uuid4(),
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="HUMAN_REVIEW_REQUIRED",
        fraction_code="84714902",
        reasoning="RGI 1: la partida 8471 comprende…",
        engine_version="0.1.0",
        confidence=Decimal("0.4200"),
        requires_human_review=pendiente,
        data_origin=origen,
    )
    d.id = DECISION_ID
    d.rgi_trace = [{"rule_id": "RGI-1", "status": "RESOLVED", "reasoning_summary": "x"}]
    return _aud(d)


def _producto() -> Product:
    p = Product(
        sku="LAP-DEMO-001",
        commercial_name='Laptop Demo 14" 8GB',
        data_origin="SYNTHETIC",
    )
    return _aud(p)


class SesionFalsa:
    def __init__(self, *, decision: ClassificationDecision | None) -> None:
        self._decision = decision
        self.agregadas: list[Any] = []
        self.commits = 0

    def get(self, modelo: type, _id: uuid.UUID, **_opciones: Any) -> Any:
        if modelo is Product:
            return _producto()
        return self._decision

    def scalars(self, _sentencia: Any) -> Any:
        r = type("R", (), {})()
        r.all = lambda: [self._decision] if self._decision else []
        return r

    def add(self, fila: Any) -> None:
        _aud(fila)
        self.agregadas.append(fila)

    def commit(self) -> None:
        self.commits += 1


def _cliente(*, decision: ClassificationDecision | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(decision=decision)
    return TestClient(app)


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    with _cliente(decision=_decision()) as c:
        yield c


# ── La bandeja ──────────────────────────────────────────────────────────────


def test_lista_lo_que_espera_revision(cliente: TestClient) -> None:
    r = cliente.get("/review")

    assert r.status_code == 200
    assert r.json()[0]["fraction_code"] == "84714902"


def test_la_bandeja_trae_contexto_para_decidir(cliente: TestClient) -> None:
    """Sin el producto, quien revisa tendría que abrir otra pantalla."""
    fila = cliente.get("/review").json()[0]

    assert fila["producto"] == 'Laptop Demo 14" 8GB'
    assert fila["sku"] == "LAP-DEMO-001"


def test_declara_si_consta_el_razonamiento(cliente: TestClient) -> None:
    """Cero pasos cambia cuánto puede fiarse quien revisa."""
    assert cliente.get("/review").json()[0]["pasos_traza"] == 1


# ── El veredicto ────────────────────────────────────────────────────────────


def test_la_correccion_no_borra_la_respuesta_de_la_maquina() -> None:
    """EL TEST QUE IMPORTA.

    Medir «fraction accuracy» (§39) exige las dos respuestas. Editar la
    original destruiría el numerador de esa métrica.
    """
    original = _decision()
    app = create_app()
    sesion = SesionFalsa(decision=original)
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        r = c.post(
            f"/review/{DECISION_ID}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": "ulises",
                "fraction_code": "84713001",
                "nota": "Es portátil completa, no unidad de proceso.",
            },
        )

    assert r.status_code == 201
    # La original conserva su fracción y su razonamiento.
    assert original.fraction_code == "84714902"
    assert original.data_origin == "SYNTHETIC"
    # Y hay una fila NUEVA con el veredicto humano.
    assert len(sesion.agregadas) == 1
    assert sesion.agregadas[0].fraction_code == "84713001"
    assert sesion.agregadas[0].data_origin == "HUMAN_VALIDATED"


def test_la_revision_comparte_el_dna_con_la_original() -> None:
    """Es lo que permite emparejarlas al evaluar."""
    original = _decision()
    app = create_app()
    sesion = SesionFalsa(decision=original)
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        c.post(
            f"/review/{DECISION_ID}",
            json={"veredicto": "CONFIRMA", "reviewer": "ulises"},
        )

    assert sesion.agregadas[0].product_dna_id == original.product_dna_id


def test_la_original_sale_de_la_bandeja() -> None:
    original = _decision()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(decision=original)

    with TestClient(app) as c:
        c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert original.requires_human_review is False


def test_la_revision_no_hereda_la_traza_del_motor() -> None:
    """Copiarla haría parecer que la persona siguió esas reglas.

    No las siguió: revisó su conclusión.
    """
    app = create_app()
    sesion = SesionFalsa(decision=_decision())
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert sesion.agregadas[0].rgi_trace is None


def test_corregir_sin_fraccion_se_rechaza(cliente: TestClient) -> None:
    """Una corrección sin la respuesta correcta no dice nada."""
    r = cliente.post(f"/review/{DECISION_ID}", json={"veredicto": "CORRIGE", "reviewer": "ulises"})

    assert r.status_code == 422


def test_la_correccion_registra_quien_la_hizo(cliente: TestClient) -> None:
    """Una corrección anónima no es auditable."""
    r = cliente.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA"})

    assert r.status_code == 422


def test_no_se_revisa_una_revision() -> None:
    """Una fila HUMAN_VALIDATED ya pasó por una persona."""
    with _cliente(decision=_decision(origen="HUMAN_VALIDATED")) as c:
        r = c.post(f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"})

    assert r.status_code == 409


def test_decision_inexistente_da_404() -> None:
    with _cliente(decision=None) as c:
        assert (
            c.post(
                f"/review/{DECISION_ID}", json={"veredicto": "CONFIRMA", "reviewer": "u"}
            ).status_code
            == 404
        )


def test_el_motivo_queda_por_escrito() -> None:
    """Sin motivo se sabe que el sistema falló, no en qué."""
    app = create_app()
    sesion = SesionFalsa(decision=_decision())
    app.dependency_overrides[get_session] = lambda: sesion

    with TestClient(app) as c:
        c.post(
            f"/review/{DECISION_ID}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": "ulises",
                "fraction_code": "84713001",
                "nota": "Es portátil completa.",
            },
        )

    razon = sesion.agregadas[0].reasoning
    assert "ulises" in razon
    assert "84714902" in razon and "84713001" in razon
    assert "Es portátil completa." in razon


# ── La bandeja dice por qué está cada caso (Persona 1, 9-sep) ────────────────


def _caso(**kwargs: Any) -> Any:
    from database.models import ClassificationDecision

    campos: dict[str, Any] = {
        "trade_flow": "IMPORT",
        "operation_date": date(2026, 3, 15),
        "status": "HUMAN_REVIEW_REQUIRED",
        "data_origin": "SYNTHETIC",
        "requires_human_review": True,
    }
    campos.update(kwargs)
    return ClassificationDecision(**campos)


def test_falta_informacion_y_desempate_no_son_lo_mismo() -> None:
    """EL TEST QUE IMPORTA.

    En un caso falta información; en el otro sobra una respuesta que nadie
    debería firmar tal cual. Un revisor que no los distingue no sabe qué le
    están pidiendo.
    """
    from apps.api.routers.review import _causas

    sin_info = _causas(_caso(status="INSUFFICIENT_INFORMATION", rgi_path=["RGI-1"]))
    desempate = _causas(_caso(rgi_path=["RGI-1", "RGI-3c"], fraction_code="85285900"))

    assert "SIN_INFORMACION" in sin_info
    assert "DESEMPATE_POR_NUMERACION" not in sin_info
    assert "DESEMPATE_POR_NUMERACION" in desempate
    assert "SIN_INFORMACION" not in desempate


def test_la_causa_del_desempate_sale_del_camino_rgi() -> None:
    """El dato ya estaba persistido: `rgi_path` lleva las reglas aplicadas."""
    from apps.api.routers.review import _causas

    assert "DESEMPATE_POR_NUMERACION" not in _causas(
        _caso(rgi_path=["RGI-1", "RGI-3a"], fraction_code="84713001")
    )
    assert "DESEMPATE_POR_NUMERACION" in _causas(
        _caso(rgi_path=["RGI-1", "RGI-3c"], fraction_code="84713001")
    )


def test_las_causas_concurren_sin_orden_de_gravedad() -> None:
    """No se inventa jerarquía: un caso puede tener varias razones a la vez."""
    from apps.api.routers.review import _causas

    causas = _causas(_caso(status="INSUFFICIENT_INFORMATION", rgi_path=["RGI-3c"]))

    assert set(causas) >= {"SIN_INFORMACION", "DESEMPATE_POR_NUMERACION"}


def test_sin_fraccion_revisar_es_proponerla_no_validarla() -> None:
    from apps.api.routers.review import _causas

    assert "SIN_FRACCION_PROPUESTA" in _causas(_caso(fraction_code=None))
    assert "SIN_FRACCION_PROPUESTA" not in _causas(
        _caso(fraction_code="84713001", rgi_path=["RGI-1"])
    )


def test_una_decision_resuelta_y_marcada_no_se_queda_muda() -> None:
    """Sin causa, el caso llega a la bandeja y nadie sabe qué se le pide."""
    from apps.api.routers.review import _causas

    assert _causas(_caso(status="RESOLVED", fraction_code="84713001", rgi_path=["RGI-1"])) == [
        "RESUELTA_PERO_MARCADA"
    ]


def test_el_identificador_de_regla_se_compara_normalizado() -> None:
    """El seed escribió `RGI1` y el motor escribe `RGI-1`.

    Comparar en crudo dejaría casos sin causa según quién los escribiera, y un
    caso sin causa es lo que esta pantalla viene a eliminar.
    """
    from apps.api.routers.review import _causas, _normalizar

    assert _normalizar("RGI-3c") == _normalizar("RGI3C") == "RGI3C"
    assert "DESEMPATE_POR_NUMERACION" in _causas(
        _caso(rgi_path=["RGI3C"], fraction_code="85285900")
    )


def test_toda_causa_tiene_explicacion() -> None:
    """Nombrar la causa sin decir qué se pide dejaría el trabajo a medias."""
    from apps.api.routers.review import CAUSAS, _causas

    todas = set()
    for fila in (
        _caso(status="INSUFFICIENT_INFORMATION"),
        _caso(rgi_path=["RGI-3c"], fraction_code="85285900"),
        _caso(fraction_code=None),
        _caso(status="RESOLVED", fraction_code="84713001", rgi_path=["RGI-1"]),
    ):
        todas.update(_causas(fila))

    assert todas <= set(CAUSAS), "hay causas sin texto"
    assert all(CAUSAS[c].strip() for c in todas)
