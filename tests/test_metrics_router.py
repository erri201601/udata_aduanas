"""Tests de la métrica de precisión (§39).

El que manda es `test_sin_revisiones_la_precision_es_desconocida_no_cero`:
con la bandeja sin usar, la precisión no es «0 %» — es desconocida.
Confundirlas haría creer que el motor falla siempre cuando lo que pasa es que
nadie ha revisado.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationDecision
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
DNA = uuid.uuid4()


def _decision(
    *,
    fraccion: str | None,
    origen: str = "SYNTHETIC",
    pendiente: bool = False,
    dna: uuid.UUID | None = None,
    minutos: int = 0,
    nico: str | None = None,
    revisa: ClassificationDecision | None = None,
) -> ClassificationDecision:
    d = ClassificationDecision(
        product_dna_id=dna or DNA,
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="RESOLVED" if fraccion else "HUMAN_REVIEW_REQUIRED",
        subheading=fraccion[:6] if fraccion else None,
        fraction_code=fraccion,
        nico_code=nico,
        data_origin=origen,
        requires_human_review=pendiente,
        reviews_decision_id=revisa.id if revisa is not None else None,
    )
    d.id = uuid.uuid4()
    d.created_at = AHORA + timedelta(minutes=minutos)
    d.updated_at = d.created_at
    d.rgi_path = []
    d.legal_rule_ids = []
    d.input_snapshot = {}
    d.missing_information = []
    return d


class SesionFalsa:
    def __init__(self, filas: list[ClassificationDecision]) -> None:
        self._filas = filas

    def scalars(self, sentencia: Any) -> Any:
        # El router pide primero los humanos y después los de máquina.
        sql = str(sentencia)
        humano = "!=" not in sql
        r = type("R", (), {})()
        r.all = lambda: [f for f in self._filas if (f.data_origin == "HUMAN_VALIDATED") is humano]
        return r


def _cliente(filas: list[ClassificationDecision]) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(filas)
    return TestClient(app)


# ── Cero declarado no es cero por ciento ────────────────────────────────────


def test_sin_revisiones_la_precision_es_desconocida_no_cero() -> None:
    """EL TEST QUE IMPORTA.

    Un 0 % diría que el motor se equivoca siempre. Lo que pasa es que nadie
    ha revisado, y son cosas distintas.
    """
    filas = [_decision(fraccion="84713001", pendiente=True) for _ in range(7)]

    with _cliente(filas) as c:
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["porcentaje"] is None
    assert m["hs_accuracy"]["porcentaje"] is None
    assert m["revisadas"] == 0
    assert m["pendientes_de_revision"] == 7


def test_declara_cuantas_esperan_para_explicar_el_vacio() -> None:
    """La cifra que dice POR QUÉ las demás están vacías."""
    filas = [_decision(fraccion=None, pendiente=True) for _ in range(7)]

    with _cliente(filas) as c:
        assert c.get("/metrics/classification").json()["pendientes_de_revision"] == 7


def test_sin_decisiones_tampoco_inventa_una_tasa() -> None:
    with _cliente([]) as c:
        m = c.get("/metrics/classification").json()

    assert m["human_review_rate"] is None
    assert m["decisiones_maquina"] == 0


# ── Con veredictos, mide ────────────────────────────────────────────────────


def _veredicto(fraccion: str, revisa: ClassificationDecision, **kw: Any) -> ClassificationDecision:
    return _decision(fraccion=fraccion, origen="HUMAN_VALIDATED", minutos=10, revisa=revisa, **kw)


def test_una_confirmacion_cuenta_como_acierto() -> None:
    maquina = _decision(fraccion="84713001")
    with _cliente([maquina, _veredicto("84713001", maquina)]) as c:
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["aciertos"] == 1
    assert m["fraction_accuracy"]["comparados"] == 1
    assert Decimal(m["fraction_accuracy"]["porcentaje"]) == Decimal("100.00")
    assert m["confirmadas"] == 1
    assert m["corregidas"] == 0


def test_una_correccion_cuenta_como_fallo() -> None:
    maquina = _decision(fraccion="84714902")
    with _cliente([maquina, _veredicto("84713001", maquina)]) as c:
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["aciertos"] == 0
    assert m["fraction_accuracy"]["comparados"] == 1
    assert Decimal(m["fraction_accuracy"]["porcentaje"]) == Decimal("0.00")
    assert m["corregidas"] == 1


def test_acertar_la_subpartida_y_fallar_la_fraccion_se_distingue() -> None:
    """Es un error mexicano, no de fondo: la subpartida está armonizada."""
    maquina = _decision(fraccion="84713002")
    with _cliente([maquina, _veredicto("84713001", maquina)]) as c:
        m = c.get("/metrics/classification").json()

    assert m["hs_accuracy"]["aciertos"] == 1  # 847130 coincide
    assert m["fraction_accuracy"]["aciertos"] == 0


# ── Lo que no se compara ────────────────────────────────────────────────────


def test_sin_nico_declarado_no_se_compara() -> None:
    """Contarlo como fallo castigaría al motor por un dato que nadie dio."""
    maquina = _decision(fraccion="84713001", nico="00")
    with _cliente([maquina, _veredicto("84713001", maquina)]) as c:
        m = c.get("/metrics/classification").json()

    assert m["nico_accuracy"]["comparados"] == 0
    assert m["nico_accuracy"]["porcentaje"] is None


def test_se_compara_contra_la_decision_que_reviso_no_contra_la_mas_reciente() -> None:
    """EL QUE ANTES FALLABA.

    Con la heurística de DNA + tiempo, el veredicto se emparejaba con la última
    decisión del DNA anterior a él —aquí, la de 85176201— aunque la persona
    hubiera revisado otra. Ahora manda el puntero.
    """
    revisada = _decision(fraccion="84714902", minutos=0)
    otra_del_mismo_dna = _decision(fraccion="85176201", minutos=5)
    filas = [revisada, otra_del_mismo_dna, _veredicto("84714902", revisada)]

    with _cliente(filas) as c:
        m = c.get("/metrics/classification").json()

    assert m["confirmadas"] == 1, "confirmó la que revisó, no corrigió la otra"
    assert m["corregidas"] == 0
    assert m["fraction_accuracy"]["comparados"] == 1


def test_un_veredicto_que_no_apunta_a_una_decision_conocida_no_se_cuenta() -> None:
    """Sin par no hay comparación posible, y no se inventa una."""
    huerfano = _decision(fraccion="84713001", origen="HUMAN_VALIDATED", minutos=10)

    with _cliente([huerfano]) as c:
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["comparados"] == 0
    assert m["revisadas"] == 0


def test_la_tasa_cuenta_decisiones_revisadas_no_filas_de_veredicto() -> None:
    """De dos decisiones, una revisada: 50 %, se cuente como se cuente."""
    revisada = _decision(fraccion="84713001")
    limpia = _decision(fraccion="84713001", minutos=1)

    with _cliente([revisada, limpia, _veredicto("84713001", revisada)]) as c:
        m = c.get("/metrics/classification").json()

    assert m["human_review_rate"] == "50.00"
    assert m["revisadas"] == 1


def test_los_porcentajes_son_decimal_no_float() -> None:
    """§22: lo que se presenta como cifra no se calcula con coma flotante."""
    from apps.api.routers.metrics import _porcentaje

    valor = _porcentaje(1, 3)
    assert isinstance(valor, Decimal)
    assert valor == Decimal("33.33")


def test_no_toca_ninguna_tabla() -> None:
    """Restricción de Persona 1: sin esquema nuevo.

    El módulo sólo lee `ClassificationDecision`; no importa
    `GroundTruthRecord` ni escribe nada.
    """
    from pathlib import Path

    fuente = Path("apps/api/routers/metrics.py").read_text(encoding="utf-8")

    assert "GroundTruthRecord" not in fuente
    assert "session.add" not in fuente
    assert "commit" not in fuente
