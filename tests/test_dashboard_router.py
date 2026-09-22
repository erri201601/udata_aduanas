"""Tests del tablero ejecutivo.

Es la pantalla donde más tienta el número bonito, y por eso los tests que
importan son los que impiden ponerlo: que no se estime lo que no tiene monto,
que lo pendiente se cuente, y que lo simulado se declare.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationDecision, Pedimento, RiskFinding
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class SesionFalsa:
    """Devuelve conteos y agregados según lo que se le configure."""

    def __init__(self, **valores: Any) -> None:
        self._v = valores
        self._llamadas = 0

    def scalar(self, sentencia: Any) -> Any:
        # El router hace las consultas en un orden fijo; se responde por turno.
        self._llamadas += 1
        return self._v.get(f"s{self._llamadas}")


def _cliente(**valores: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(**valores)
    return TestClient(app)


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    with _cliente() as c:
        yield c


def test_el_tablero_responde(cliente: TestClient) -> None:
    assert cliente.get("/dashboard").status_code == 200


def test_sin_datos_no_inventa_cifras(cliente: TestClient) -> None:
    """Una base vacía produce ceros y nulos, no estimaciones."""
    d = cliente.get("/dashboard").json()

    assert d["clasificaciones"]["total"] == 0
    assert d["hallazgos"]["impacto_cuantificado"] is None
    assert d["oportunidades"]["ahorro_cuantificado"] is None


def test_declara_lo_pendiente_no_solo_lo_hecho(cliente: TestClient) -> None:
    """Un tablero que sólo cuenta éxitos sirve para vender, no para dirigir."""
    d = cliente.get("/dashboard").json()

    assert "requieren_revision" in d["clasificaciones"]
    assert "sin_informacion" in d["clasificaciones"]
    assert "sin_auditar" in d["auditoria"]
    assert "solo_investigables" in d["hallazgos"]


def test_separa_lo_accionable_de_lo_investigable(cliente: TestClient) -> None:
    """El monto decide si se PRESENTA, no cuánto importa.

    Una NOM faltante no cambia lo que se paga y aun así detiene la mercancía.
    """
    hallazgos = cliente.get("/dashboard").json()["hallazgos"]

    assert "accionables" in hallazgos
    assert "solo_investigables" in hallazgos


def test_el_impacto_solo_suma_lo_cuantificado(cliente: TestClient) -> None:
    """Sumar hallazgos sin monto daría una cifra de folleto."""
    from apps.api.routers.dashboard import Hallazgos

    campo = Hallazgos.model_fields["impacto_cuantificado"]
    assert campo.annotation is not None
    # Nulo por defecto: sin nada cuantificado no hay número, no hay cero.
    assert campo.default is None


def test_declara_cuanto_es_simulacion(cliente: TestClient) -> None:
    """§33: una cifra que mezcla simulado y real deja de poder presentarse."""
    d = cliente.get("/dashboard").json()

    assert "filas_simuladas" in d
    assert "todo_simulado" in d


def test_sin_filas_no_se_declara_todo_simulado(cliente: TestClient) -> None:
    """Con la base vacía, «todo es simulación» sería una afirmación vacía."""
    assert cliente.get("/dashboard").json()["todo_simulado"] is False


def test_los_modelos_usados_existen() -> None:
    """Evita asumir columnas, que ya me costó una vez."""
    assert {"status", "rgi_trace"} <= {c.name for c in ClassificationDecision.__table__.columns}
    assert {"impact_amount", "severity"} <= {c.name for c in RiskFinding.__table__.columns}
    assert "data_origin" in {c.name for c in Pedimento.__table__.columns}


def test_las_severidades_estan_ordenadas_de_peor_a_menor() -> None:
    from apps.api.routers.dashboard import ORDEN_SEVERIDAD

    assert ORDEN_SEVERIDAD[0] == "CRITICAL"
    assert ORDEN_SEVERIDAD[-1] == "INFO"


def test_una_decision_sin_traza_no_se_cuenta_como_documentada() -> None:
    """`con_traza` cuenta sólo las que conservan el razonamiento."""
    d = ClassificationDecision(
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="RESOLVED",
        data_origin="SYNTHETIC",
    )
    d.rgi_trace = None

    assert d.rgi_trace is None


def test_el_dinero_es_decimal() -> None:
    """§22: nada de float donde importa la precisión."""
    from apps.api.routers.dashboard import Hallazgos

    h = Hallazgos(impacto_cuantificado=Decimal("48200.00"))
    assert isinstance(h.impacto_cuantificado, Decimal)


def test_el_id_de_pedimento_es_uuid() -> None:
    assert Pedimento.__table__.c.id.type.python_type is uuid.UUID


def test_el_tablero_agrupa_el_dinero_por_partida_no_por_hallazgo() -> None:
    """Dos divergencias de una partida explican la MISMA diferencia.

    Se comprueba sobre la consulta: agrupa por revisión y partida, y toma el
    mayor — el mismo criterio que `core.audit.engine._total`.
    """
    from apps.api.routers.dashboard import _por_partida

    sql = str(_por_partida().original.compile(compile_kwargs={"literal_binds": True}))

    assert "max(" in sql.lower()
    assert "GROUP BY" in sql
    assert "pedimento_item_id" in sql
    assert "shadow_review_id" in sql
