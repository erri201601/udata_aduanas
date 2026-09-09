"""Tests del Regulatory Sentinel.

La tentación de esta pantalla no es el número bonito: es PARECER QUE VIGILA.
Los tests que importan son los que impiden que un cero se lea como calma —
`eventos_dof: 0` con el watcher sin arrancar significa «nadie está mirando»—
y los que impiden afirmar impacto sobre decisiones que no guardaron qué
normas citaron.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationDecision, LegalDocument, LegalRule, RegulatoryEvent
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


class SesionFalsa:
    """Responde `scalar` por turno y `execute` con listas configuradas.

    El router hace sus consultas en orden fijo: tres conteos de normas, el
    de eventos, y luego las tres consultas de filas. Se responde igual.
    """

    def __init__(self, *, escalares: list[Any] | None = None, filas: list[list[Any]] | None = None):
        self._escalares = list(escalares or [])
        self._filas = list(filas or [])

    def scalar(self, _sentencia: Any) -> Any:
        return self._escalares.pop(0) if self._escalares else 0

    def execute(self, _sentencia: Any) -> Any:
        lote = self._filas.pop(0) if self._filas else []
        return type("Resultado", (), {"all": lambda _self, _l=lote: _l})()


def _cliente(**kwargs: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(**kwargs)
    return TestClient(app)


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    with _cliente() as c:
        yield c


def test_el_centinela_responde(cliente: TestClient) -> None:
    assert cliente.get("/sentinel").status_code == 200


def test_sin_eventos_no_declara_vigilancia(cliente: TestClient) -> None:
    """El fallo que esta pantalla existe para impedir.

    `eventos_dof: 0` sobre un watcher que nunca arrancó no es «sin novedades».
    Sin `vigilancia_automatica` la pantalla no puede distinguir las dos cosas.
    """
    d = cliente.get("/sentinel").json()

    assert d["eventos_dof"] == 0
    assert d["vigilancia_automatica"] is False


def test_con_eventos_si_declara_vigilancia() -> None:
    # normas_totales, vigentes, caducas, eventos
    with _cliente(escalares=[10, 8, 2, 3, 0, 0, 0]) as c:
        d = c.get("/sentinel").json()

    assert d["eventos_dof"] == 3
    assert d["vigilancia_automatica"] is True


def test_la_fecha_manda_sobre_la_vigencia(cliente: TestClient) -> None:
    """No es un filtro cosmético: en otra fecha la norma era otra (§14)."""
    d = cliente.get("/sentinel?fecha=2024-03-15").json()

    assert d["fecha"] == "2024-03-15"


def test_una_fecha_invalida_se_rechaza(cliente: TestClient) -> None:
    assert cliente.get("/sentinel?fecha=ayer").status_code == 422


def test_sin_normas_citadas_el_impacto_no_es_trazable() -> None:
    """Decisiones sin `legal_rule_ids` NO se cuentan como limpias."""
    # ...conteos de normas y eventos, luego total=7 decisiones, con_normas=0
    with _cliente(escalares=[366, 351, 15, 0, 7, 0, 0]) as c:
        impacto = c.get("/sentinel").json()["impacto"]

    assert impacto["decisiones"] == 7
    assert impacto["con_normas_citadas"] == 0
    assert impacto["sin_normas_citadas"] == 7
    assert impacto["trazable"] is False


def test_con_normas_citadas_el_impacto_es_trazable() -> None:
    with _cliente(escalares=[366, 351, 15, 0, 7, 5, 2]) as c:
        impacto = c.get("/sentinel").json()["impacto"]

    assert impacto["con_normas_citadas"] == 5
    assert impacto["sin_normas_citadas"] == 2
    assert impacto["afectadas"] == 2
    assert impacto["trazable"] is True


def test_un_documento_no_oficial_no_puede_fundamentar() -> None:
    """§33: el TIGIE de demo va marcado, no mezclado con la Ley Aduanera."""
    filas_corpus = [
        ("LEY_ADUANERA", "Ley Aduanera", "LAW", "OFFICIAL", date(2025, 11, 19), None, 274),
        ("TIGIE", "TIGIE (demo)", "TARIFF", "SYNTHETIC", date(2022, 1, 1), None, 0),
    ]
    with _cliente(escalares=[274, 274, 0, 0, 0, 0, 0], filas=[filas_corpus, [], []]) as c:
        d = c.get("/sentinel").json()

    oficial, sintetico = d["corpus"]
    assert oficial["es_fuente_oficial"] is True
    assert sintetico["es_fuente_oficial"] is False
    assert d["corpus_sintetico"] == 1


def test_las_columnas_usadas_existen() -> None:
    """Evita asumir columnas, que ya me costó una vez."""
    assert {"rule_number", "valid_from", "valid_to", "heading_text", "path"} <= {
        c.name for c in LegalRule.__table__.columns
    }
    assert {"short_name", "title", "kind", "data_origin"} <= {
        c.name for c in LegalDocument.__table__.columns
    }
    assert {"event_kind", "effective_date"} <= {c.name for c in RegulatoryEvent.__table__.columns}
    assert "legal_rule_ids" in {c.name for c in ClassificationDecision.__table__.columns}


def test_la_regla_temporal_es_la_del_maestro() -> None:
    """`valid_from <= fecha AND (valid_to IS NULL OR valid_to >= fecha)`."""
    from apps.api.routers.sentinel import _vigentes

    sql = str(_vigentes(date(2024, 3, 15)).compile(compile_kwargs={"literal_binds": True}))

    assert "valid_from <= '2024-03-15'" in sql
    assert "valid_to IS NULL" in sql
    assert "valid_to >= '2024-03-15'" in sql


def test_las_olas_de_reforma_no_se_presentan_como_eventos_del_dof() -> None:
    """Son deducción del corpus, no publicación. El modelo lo dice."""
    from apps.api.routers.sentinel import OlaDeReforma

    assert "DOF" in (OlaDeReforma.__doc__ or "")
