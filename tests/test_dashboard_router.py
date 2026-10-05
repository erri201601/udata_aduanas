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
import sqlalchemy as sa
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
        #: El SQL de cada consulta. La sesión falsa ignora los WHERE, así que
        #: el acotamiento sólo se puede fijar mirando la sentencia.
        self.sql: list[str] = []

    def scalar(self, sentencia: Any) -> Any:
        # El router hace las consultas en un orden fijo; se responde por turno.
        self._llamadas += 1
        self.sql.append(str(sentencia))
        return self._v.get(f"s{self._llamadas}")

    def execute(self, sentencia: Any) -> Any:
        """El reparto por severidad: filas, no un escalar."""
        self.sql.append(str(sentencia))
        return iter(self._v.get("severidades", ()))

    def scalars(self, sentencia: Any) -> Any:
        """Las monedas presentes, que son un conjunto y no un escalar.

        No se responde por turno como `scalar`: el tablero sólo suma cuando hay
        UNA moneda, así que el número de llamadas a `scalar` depende de lo que
        devuelva esto. Encadenar los dos contadores haría que configurar una
        mezcla de monedas corriera el resto de las respuestas.
        """
        self.sql.append(str(sentencia))
        clave = "monedas_ahorro" if "opportunity_findings" in str(sentencia) else "monedas"
        return iter(self._v.get(clave, ()))


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


def test_el_tablero_cuenta_solo_la_ultima_revision_de_cada_pedimento() -> None:
    """Auditar un pedimento dos veces no lo hace deber el doble.

    La exposición de un pedimento no es la suma de las veces que lo hemos
    mirado (Persona 1, 22-sep).
    """
    from apps.api.routers.dashboard import _por_partida
    from sqlalchemy.dialects import postgresql

    # Con el dialecto de Postgres: `DISTINCT ON` no existe en el genérico, y
    # comprobarlo ahí daría un falso negativo.
    sql = str(
        _por_partida().original.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "DISTINCT ON" in sql.upper(), "una revisión por pedimento"
    assert "shadow_reviews.created_at DESC" in sql, "la más reciente"
    assert "shadow_review_id IS NULL" in sql, "los hallazgos sin revisión no se pierden"


# ── El tablero cuenta el estado actual (Persona 1, 28-sep) ─────────────────


def test_los_hallazgos_se_cuentan_de_la_revision_vigente() -> None:
    """Cada re-auditoría deja sus hallazgos. Sin acotar, el tablero anunciaba
    467 donde las revisiones vigentes tenían 89 — cinco veces la cifra real, y
    creciendo cada vez que alguien volvía a medir."""
    sesion = SesionFalsa()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion
    with TestClient(app) as c:
        c.get("/dashboard")

    conteos = [q for q in sesion.sql if "count(" in q.lower() and "risk_findings" in q]
    assert conteos, "no se contaron hallazgos"
    assert all("shadow_reviews" in q for q in conteos), (
        "algún conteo de hallazgos no se acota a la revisión vigente"
    )


def test_la_peor_severidad_tambien_sale_de_la_vigente() -> None:
    """Una auditoría vieja con un CRITICAL ya corregido no puede seguir
    marcando el tablero en rojo."""
    sesion = SesionFalsa()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion
    with TestClient(app) as c:
        c.get("/dashboard")

    severidad = [q for q in sesion.sql if "severity" in q and "count(" not in q.lower()]
    assert severidad and all("shadow_reviews" in q for q in severidad)


# ── Dos monedas no se suman (Persona 1, 5-oct) ─────────────────────────────


def test_con_dos_monedas_no_hay_total_de_impacto() -> None:
    """El Espejo ya aplicaba esta disciplina y el tablero no.

    Sumaba a ciegas y etiquetaba el resultado con la PRIMERA moneda que
    encontraba: un número que parece dinero, no lo es, y encima afirma de qué
    moneda es.
    """
    with _cliente(monedas=("MXN", "USD")) as c:
        h = c.get("/dashboard").json()["hallazgos"]

    assert h["monedas_mezcladas"] is True
    assert h["impacto_cuantificado"] is None, "con dos monedas no hay total"
    assert h["impacto_moneda"] is None, "ni divisa que ponerle"


def test_con_una_sola_moneda_si_hay_total_de_impacto() -> None:
    """La cautela no puede comerse el caso normal."""
    with _cliente(monedas=("MXN",)) as c:
        h = c.get("/dashboard").json()["hallazgos"]

    assert h["monedas_mezcladas"] is False
    assert h["impacto_moneda"] == "MXN"


def test_con_dos_monedas_no_hay_total_de_ahorro() -> None:
    """Mismo criterio en el ahorro, que es el número que alguien querría cobrar."""
    with _cliente(monedas_ahorro=("MXN", "USD")) as c:
        o = c.get("/dashboard").json()["oportunidades"]

    assert o["monedas_mezcladas"] is True
    assert o["ahorro_cuantificado"] is None
    assert o["ahorro_moneda"] is None


# ── El ahorro simulado se declara (Persona 1, 5-oct) ───────────────────────


def test_las_oportunidades_entran_en_el_censo_de_simuladas() -> None:
    """Un ahorro simulado tiene que contar para `todo_simulado`.

    Mientras no contaba, bastaba cargar un producto real para que el aviso de
    simulación desapareciera y el dinero inventado se quedara en pantalla sin
    marca ninguna. Es el dato de la consola que alguien querría cobrar.
    """
    sesion = SesionFalsa()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion
    with TestClient(app) as c:
        d = c.get("/dashboard").json()

    assert "simuladas" in d["oportunidades"], "la cifra tiene que viajar a la consola"
    censo = [
        q
        for q in sesion.sql
        if "count(" in q.lower() and "opportunity_findings" in q and "is_simulation" in q
    ]
    assert censo, "las oportunidades simuladas no se cuentan"


def test_una_oportunidad_puede_decir_si_es_simulacion() -> None:
    """La columna faltaba y el repositorio se la pasaba igual.

    `POST /pedimentos/{id}/review` reventaba con un 500 en cuanto un pedimento
    producía una oportunidad —uno de dieciséis del corpus, por eso llevaba
    meses escondido—. El 500 era el síntoma; el defecto era que un ahorro no
    podía decir si sale de una operación inventada.
    """
    from database.models import OpportunityFinding

    assert "is_simulation" in {c.name for c in OpportunityFinding.__table__.columns}
    columna = OpportunityFinding.__table__.c.is_simulation
    assert not columna.nullable, "igual que en RiskFinding: o es simulación o no lo es"


# ── El dictamen es del caso, no de la decisión (Persona 1, 5-oct) ──────────


def test_las_dictaminadas_se_cuentan_por_ficha_no_por_decision() -> None:
    """Reclasificar no borra lo que dijo una persona.

    Los trece dictámenes de César apuntan con `reviews_decision_id` a la
    decisión concreta que revisaron, y eso está bien. Pero preguntar SÓLO por
    esa decisión convierte el dictamen en algo que caduca al volver a
    clasificar: reclasificar los 181 productos del corpus dejó el tablero en
    **cero dictaminadas** cuando enseñaba 7. Los veredictos seguían íntegros en
    la base; la pantalla decía que nadie había mirado nada.

    La unidad es la misma que usa `_la_decision_vigente` tres líneas más
    arriba: la ficha. «Un producto es un caso, no una fila por cada vez que se
    clasificó.»

    Se comprueba sobre el SQL porque la sesión falsa ignora los WHERE.
    """
    from apps.api.routers.dashboard import _ya_dictaminada

    sql = str(
        sa.select(sa.func.count())
        .select_from(ClassificationDecision)
        .where(_ya_dictaminada())
        .compile(compile_kwargs={"literal_binds": True})
    )

    assert "reviews_decision_id" in sql, "sigue preguntando por el veredicto"
    assert "product_dna_id" in sql, (
        "sin la ficha, el dictamen caduca en cuanto el motor vuelve a contestar"
    )


def test_una_decision_sin_ficha_tambien_puede_estar_dictaminada() -> None:
    """Sin `product_dna_id` no hay caso al que agruparla.

    El camino directo —un veredicto que apunta a ESA decisión— tiene que
    seguir existiendo, o las decisiones sin ficha perderían su dictamen por
    una puerta que se abrió para conservarlo.
    """
    from apps.api.routers.dashboard import _ya_dictaminada

    sql = str(
        sa.select(sa.func.count())
        .select_from(ClassificationDecision)
        .where(_ya_dictaminada())
        .compile(compile_kwargs={"literal_binds": True})
    )

    assert sql.count("reviews_decision_id") >= 2, "los dos caminos, no sólo el de la ficha"
    assert "OR" in sql.upper()


# ── El SQL del tablero y el agregador del motor, de acuerdo ────────────────


@pytest.mark.parametrize(
    ("montos", "esperado"),
    [
        # Sólo causas: se toma UNA, la mayor. Explican el mismo delta.
        ([("11600.00", "LINEA_COMPLETA"), ("11600.00", "LINEA_COMPLETA")], "11600.00"),
        ([("11600.00", "LINEA_COMPLETA"), ("4000.00", "LINEA_COMPLETA")], "11600.00"),
        # Sólo contribuciones: se suman. Son deudas distintas.
        ([("9645.90", "UNA_CONTRIBUCION"), ("1543.34", "UNA_CONTRIBUCION")], "11189.24"),
        # Las dos clases: manda el error de cálculo y NO se suma el de la
        # fracción. Sumar daba 15,600 donde se deben 13,872.
        ([("4000.00", "UNA_CONTRIBUCION"), ("11600.00", "LINEA_COMPLETA")], "4000.00"),
        # Sin alcance: las filas anteriores a la columna eran de línea completa.
        ([("11600.00", None), ("11600.00", None)], "11600.00"),
    ],
)
def test_el_agregador_del_motor_decide_cada_combinacion(
    montos: list[tuple[str, str | None]], esperado: str
) -> None:
    """El criterio vive en una sola función, y éstos son sus cuatro casos.

    El SQL del tablero hace lo mismo sobre la base; el test de abajo comprueba
    que la consulta tenga las dos ramas en vez de un `max()` a secas.
    """
    from core.audit import total_por_partida

    total = total_por_partida((Decimal(m), a) for m, a in montos)
    assert total == Decimal(esperado)


def test_la_consulta_del_tablero_no_deduplica_las_contribuciones() -> None:
    """Un `max()` a secas se quedaría con la mayor y perdería la otra.

    Se comprueba sobre el SQL porque la sesión falsa ignora los WHERE. Lo que
    se fija es que la consulta distinga el alcance: sin eso, un IGI y un IVA
    mal calculados en la misma partida reportarían sólo el mayor.
    """
    from apps.api.routers.dashboard import _por_partida

    sql = str(_por_partida().original.compile(compile_kwargs={"literal_binds": True}))

    assert "impact_scope" in sql, "la consulta tiene que leer el alcance"
    assert "sum(" in sql.lower(), "las contribuciones se suman"
    assert "max(" in sql.lower(), "las causas se deduplican"
