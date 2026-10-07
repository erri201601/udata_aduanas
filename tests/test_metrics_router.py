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
    def __init__(self, filas: list[ClassificationDecision], *, pendientes: int = 0) -> None:
        self._filas = filas
        self._pendientes = pendientes

    def scalar(self, _sentencia: Any) -> int:
        # El único `scalar` del router es el conteo de la bandeja, con la
        # definición de `database.repositories.preguntas` (ADR 0008). Eso es
        # SQL —`DISTINCT ON`, `NOT EXISTS`— y una sesión falsa no lo ejecuta:
        # aquí se fija la cifra y se comprueba que el campo la informa. Que la
        # cifra sea la de la bandeja lo prueba
        # `tests/test_contadores_de_pendientes.py` contra Postgres.
        return self._pendientes

    def scalars(self, sentencia: Any) -> Any:
        # El router pide primero los humanos y después los de máquina.
        sql = str(sentencia)
        humano = "!=" not in sql
        r = type("R", (), {})()
        r.all = lambda: [f for f in self._filas if (f.data_origin == "HUMAN_VALIDATED") is humano]
        return r


def _cliente(filas: list[ClassificationDecision], *, pendientes: int = 0) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(filas, pendientes=pendientes)
    return TestClient(app)


# ── Cero declarado no es cero por ciento ────────────────────────────────────


def test_sin_revisiones_la_precision_es_desconocida_no_cero() -> None:
    """EL TEST QUE IMPORTA.

    Un 0 % diría que el motor se equivoca siempre. Lo que pasa es que nadie
    ha revisado, y son cosas distintas.
    """
    filas = [_decision(fraccion="84713001", pendiente=True) for _ in range(7)]

    # Siete decisiones de la MISMA ficha son UN caso en la bandeja (ADR 0008).
    with _cliente(filas, pendientes=1) as c:
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["porcentaje"] is None
    assert m["hs_accuracy"]["porcentaje"] is None
    assert m["revisadas"] == 0
    assert m["pendientes_de_revision"] == 1


def test_declara_cuantas_esperan_para_explicar_el_vacio() -> None:
    """La cifra que dice POR QUÉ las demás están vacías: los casos de la bandeja.

    Antes contaba filas con la bandera —siete decisiones de una misma ficha
    eran «7 esperando»— y el 7-oct decía 4 610 con la bandeja vacía.
    """
    filas = [_decision(fraccion=None, pendiente=True) for _ in range(7)]

    with _cliente(filas, pendientes=1) as c:
        assert c.get("/metrics/classification").json()["pendientes_de_revision"] == 1


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


def test_abstenerse_no_cuenta_como_fallar() -> None:
    """EL TEST QUE IMPORTA (hallazgo del 30-sep, el día de la demo).

    El motor no dio fracción y la persona sí. Eso no es un error del motor: es
    §8.2 funcionando —«sin información suficiente, HUMAN_REVIEW_REQUIRED»— y
    contarlo como fallo mide cobertura y lo presenta como puntería.

    Con datos reales la diferencia era esto:

        antes   fraction_accuracy  0.00 % sobre 13
        ahora   0 de 1 comparado, 12 abstenciones
        y hs_accuracy pasó de 7.69 % a 100 % sobre un caso

    Es la misma regla que el fichero ya aplicaba cuando quien no declaraba era
    la persona. Faltaba al revés.
    """
    maquina = _decision(fraccion=None)
    with _cliente([maquina, _veredicto("73239305", maquina)]) as c:
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["comparados"] == 0, "no hay con qué comparar"
    assert m["fraction_accuracy"]["aciertos"] == 0
    assert m["fraction_accuracy"]["abstenciones"] == 1
    assert m["fraction_accuracy"]["porcentaje"] is None, "desconocido, no cero"


def test_la_abstencion_no_diluye_el_porcentaje_de_los_que_si_contesto() -> None:
    """Dos casos: en uno contestó y acertó, en el otro se abstuvo.

    El porcentaje es 100 % sobre uno, no 50 % sobre dos. Y la abstención se
    declara al lado para que nadie lea el 100 % como cobertura.
    """
    acerto = _decision(fraccion="84713001")
    callo = _decision(fraccion=None, dna=uuid.uuid4(), minutos=1)
    filas = [acerto, callo, _veredicto("84713001", acerto), _veredicto("73239305", callo)]
    with _cliente(filas) as c:
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["aciertos"] == 1
    assert m["fraction_accuracy"]["comparados"] == 1
    assert m["fraction_accuracy"]["abstenciones"] == 1
    assert Decimal(m["fraction_accuracy"]["porcentaje"]) == Decimal("100.00")


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


# ── El motor de hoy, no el de aquel día (Persona 1, 5-oct) ─────────────────


def test_la_precision_historica_no_es_la_del_motor_de_hoy() -> None:
    """EL CASO REAL, Y ES EXACTO Y ENGAÑA A LA VEZ.

    El único par comparable del corpus es la vajilla de cerámica del 28 de
    septiembre: el motor dijo 69120003 («De Talavera») y la persona 69120099
    («Los demás»). `fraction_accuracy` sale 0.00 % por eso.

    Y ese defecto se arregló el 28 de septiembre, el mismo día: hoy el motor
    contesta 69120099 en ese caso. El 0 % mide al motor **como era**, congelado
    en el momento en que alguien lo revisó, y nada en pantalla lo decía.

    Las dos cifras valen y dicen cosas distintas. Las dos se publican.
    """
    revisada = _decision(fraccion="69120003", minutos=0)
    ahora = _decision(fraccion="69120099", minutos=60)
    filas = [revisada, ahora, _veredicto("69120099", revisada)]

    with _cliente(filas) as c:
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["porcentaje"] == "0.00", "la traza histórica no se toca"
    assert m["contra_el_motor_de_hoy"]["coinciden"] == 1, "el motor de hoy sí coincide"
    assert m["contra_el_motor_de_hoy"]["discrepan"] == 0


def test_que_el_motor_de_hoy_se_abstenga_no_es_discrepar() -> None:
    """§8.2: negarse no es equivocarse.

    Es cobertura que falta, y por eso va en su propia casilla en vez de
    sumarse a `coinciden` o a `discrepan`.
    """
    revisada = _decision(fraccion="84714902", minutos=0)
    se_abstiene = _decision(fraccion=None, minutos=60)
    filas = [revisada, se_abstiene, _veredicto("84713001", revisada)]

    with _cliente(filas) as c:
        h = c.get("/metrics/classification").json()["contra_el_motor_de_hoy"]

    assert h["se_abstiene"] == 1
    assert h["discrepan"] == 0
    assert h["coinciden"] == 0


def test_un_motor_que_hoy_discrepa_se_declara() -> None:
    """Es el número que hay que vigilar: si sube, una mejora rompió algo que
    una persona ya había validado."""
    revisada = _decision(fraccion="84714902", minutos=0)
    discrepa = _decision(fraccion="85176201", minutos=60)
    filas = [revisada, discrepa, _veredicto("84713001", revisada)]

    with _cliente(filas) as c:
        h = c.get("/metrics/classification").json()["contra_el_motor_de_hoy"]

    assert h["discrepan"] == 1
    assert h["coinciden"] == 0


def test_la_comparacion_de_hoy_va_por_ficha_no_por_la_decision_mas_reciente() -> None:
    """Cada veredicto se compara con el estado vigente de SU ficha.

    `ficha_nueva` es la decisión más reciente de toda la tabla, y es de otra
    ficha. Tomar «la última» a secas compararía el veredicto contra una
    respuesta a otra pregunta — el mismo error que la heurística de DNA+tiempo
    ya costó una vez, y que `reviews_decision_id` vino a resolver.
    """
    otro_dna = uuid.uuid4()
    la_suya = _decision(fraccion="84713001", minutos=0)
    ficha_nueva = _decision(fraccion="85176201", dna=otro_dna, minutos=60)
    filas = [la_suya, ficha_nueva, _veredicto("84713001", la_suya)]

    with _cliente(filas) as c:
        h = c.get("/metrics/classification").json()["contra_el_motor_de_hoy"]

    assert h["coinciden"] == 1, "la vigente de su ficha dice lo mismo que la persona"
    assert h["discrepan"] == 0, "la más reciente de OTRA ficha no entra en la comparación"


def test_manda_el_ultimo_veredicto_del_caso() -> None:
    """Un veredicto que el clasificador sustituyó no discrepa de nadie (7-oct).

    Contando todos, la pantalla decía «discrepan 2»: eran dos veredictos viejos
    ya reemplazados por el propio César. Con el último de cada caso, cero.
    """
    primera = _decision(fraccion="73053199", minutos=0)
    segunda = _decision(fraccion=None, pendiente=True, minutos=30)
    hoy = _decision(fraccion="73051291", minutos=90)
    viejo = _veredicto("73053199", primera)
    viejo.created_at = AHORA + timedelta(minutes=10)
    nuevo = _veredicto("73051291", segunda)
    nuevo.created_at = AHORA + timedelta(minutes=40)

    with _cliente([primera, segunda, hoy, viejo, nuevo]) as c:
        h = c.get("/metrics/classification").json()["contra_el_motor_de_hoy"]

    assert h["coinciden"] == 1
    assert h["discrepan"] == 0, "el veredicto sustituido no cuenta"


def test_un_falta_informacion_posterior_saca_el_caso_de_la_comparacion() -> None:
    primera = _decision(fraccion="73121099", minutos=0)
    hoy = _decision(fraccion="73121005", minutos=90)
    viejo = _veredicto("73121099", primera)
    viejo.created_at = AHORA + timedelta(minutes=10)
    falta = _veredicto(None, primera)
    falta.created_at = AHORA + timedelta(minutes=40)

    with _cliente([primera, hoy, viejo, falta]) as c:
        h = c.get("/metrics/classification").json()["contra_el_motor_de_hoy"]

    assert h["coinciden"] == 0
    assert h["discrepan"] == 0, "el clasificador retiró su fracción: no hay con qué discrepar"
