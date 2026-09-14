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


# ── Reforma frente a entrada en vigor (Persona 1, 14-sep) ────────────────────
#
# Los números de las filas RGCE reproducen el reconocimiento de Persona 2
# (docs/RECONOCIMIENTO_RGCE_2026.md): ~535 reglas con valid_from 2026-01-01 y 2
# con 2026-02-02. Son DOBLES DE PRUEBA de una carga que todavía no existe, no
# dato cargado.


def _fila(
    documento: str,
    dia: date,
    *,
    citan: int = 0,
    no_citan: int = 0,
    kind: str = "LAW",
    vigencia_doc: date | None = None,
) -> tuple[Any, ...]:
    muestra = [f"{i}" for i in range(1, 8)]
    return (
        documento,
        kind,
        vigencia_doc,
        dia,
        citan,
        no_citan,
        muestra if citan else None,
        muestra if no_citan else None,
    )


def test_una_resolucion_anual_no_es_una_ola_de_reforma() -> None:
    """EL TEST QUE IMPORTA.

    «535 normas reformadas el 2026-01-01» sería falso: la RGCE se sustituye
    entera cada año. Ni una de esas reglas puede aparecer como reforma.
    """
    from apps.api.routers.sentinel import _clasificar_olas

    rgce = date(2026, 1, 1)
    reformas, entradas = _clasificar_olas(
        [
            _fila("RGCE_2026", rgce, no_citan=535, kind="RULE", vigencia_doc=rgce),
            _fila("RGCE_2026", date(2026, 2, 2), no_citan=2, kind="RULE", vigencia_doc=rgce),
        ]
    )

    assert reformas == []
    principal = next(e for e in entradas if e.fecha == rgce)
    assert principal.normas == 535
    assert principal.tipo == "DOCUMENTO_COMPLETO"
    diferida = next(e for e in entradas if e.fecha == date(2026, 2, 2))
    assert diferida.tipo == "SIN_REFORMA_REGISTRADA", "no se afirma que sea transitorio"


def test_la_ley_aduanera_2025_sigue_siendo_reforma_aunque_coincida_con_su_documento() -> None:
    """Por qué `kind` no decide: estas 80 son reformas reales de un `LAW` cuya
    vigencia de documento es ese mismo día. Lo que decide es la nota."""
    from apps.api.routers.sentinel import _clasificar_olas

    dia = date(2025, 11, 19)
    reformas, entradas = _clasificar_olas([_fila("LEY_ADUANERA", dia, citan=80, vigencia_doc=dia)])

    assert [(r.documento, r.normas) for r in reformas] == [("LEY_ADUANERA", 80)]
    assert entradas == []


def test_un_mismo_dia_puede_tener_reforma_y_entrada_en_vigor() -> None:
    """Ley Aduanera 1995-12-15: 54 de la publicación original y 1 derogada ese día.
    Colapsarlo en una sola cosa mentiría sobre 54 o sobre 1."""
    from apps.api.routers.sentinel import _clasificar_olas

    dia = date(1995, 12, 15)
    reformas, entradas = _clasificar_olas(
        [_fila("LEY_ADUANERA", dia, citan=1, no_citan=54, vigencia_doc=date(2025, 11, 19))]
    )

    assert reformas[0].normas == 1
    assert entradas[0].normas == 54
    assert entradas[0].tipo == "SIN_REFORMA_REGISTRADA"


def test_se_agrupa_por_documento_no_solo_por_dia() -> None:
    """Lo que dos documentos hicieron el mismo día no se suma en una ola."""
    from apps.api.routers.sentinel import _clasificar_olas

    dia = date(2026, 1, 1)
    reformas, _ = _clasificar_olas(
        [_fila("LEY_ADUANERA", dia, citan=3), _fila("LIGIE", dia, citan=5, kind="TARIFF")]
    )

    assert sorted((r.documento, r.normas) for r in reformas) == [
        ("LEY_ADUANERA", 3),
        ("LIGIE", 5),
    ]


def test_lo_que_no_cabe_en_el_tope_se_cuenta() -> None:
    """Las olas viejas no pueden desaparecer sin que nada lo diga."""
    from apps.api.routers.sentinel import TOPE_REFORMAS

    filas = [_fila("LEY_ADUANERA", date(1990 + i, 1, 1), citan=1) for i in range(TOPE_REFORMAS + 5)]
    corpus: list[Any] = []
    with _cliente(escalares=[0, 0, 0, 0, 0, 0, 0], filas=[corpus, filas, []]) as c:
        d = c.get("/sentinel").json()

    assert len(d["reformas"]) == TOPE_REFORMAS
    assert d["total_olas"] == TOPE_REFORMAS + 5
    # Las que caben son las más recientes.
    assert d["reformas"][0]["fecha"] == f"{1990 + TOPE_REFORMAS + 4}-01-01"


def test_la_nota_se_compara_con_la_fecha_en_formato_del_dof() -> None:
    """«Párrafo reformado DOF 19-11-2025»: día-mes-año, no ISO."""
    from apps.api.routers.sentinel import _cita_su_fecha

    sql = str(_cita_su_fecha().compile())

    assert "to_char" in sql.lower()
    assert "reform_note" in sql
    assert "coalesce" in sql.lower(), "sin nota no consta reforma: NULL tiene que dar falso"
