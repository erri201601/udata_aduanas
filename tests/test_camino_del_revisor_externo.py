"""El camino de entrada de un veredicto del cliente, de punta a punta (§39).

QUÉ DEMUESTRA ESTE ARCHIVO

Que un veredicto externo entra por la bandeja y sale convertido en un número
real en `fraction_accuracy`. Hoy la métrica devuelve `null` —desconocida, no
mala— porque nadie ha revisado; cuando lleguen los diez pedimentos del cliente no
queremos descubrir entonces si el camino funciona.

POR QUÉ NO ES UN TEST DE INTEGRACIÓN

Porque los 23 tests `integration` de este repo NO CORREN, ni en local ni en
CI: `pg_session` borra `POSTGRES_PASSWORD` y lee `.env`, que en CI no existe,
así que siempre se saltan. La última corrida de CI dice «649 passed, 23
skipped», igual que en local. Un test que no arranca no es un test que pasa, y
poner aquí uno de esos habría sido cobertura de mentira justo en la pieza que
más importa medir.

Así que el camino se recorre con las funciones reales —`revisar()` y
`precision()`, sin mocks de la lógica— sobre una sesión falsa. Lo que no
puede comprobar así es SQL, y eso ya lo cubren los tests de `metrics.py`.

El camino se verificó además a mano contra el Postgres compartido, en una
transacción revertida: la métrica pasó de `porcentaje: null · comparados: 0` a
`porcentaje: 0.00 · comparados: 1 · corregidas: 1`, y la base quedó con cero
veredictos humanos, como estaba.

NO SE INVENTA NINGÚN VEREDICTO

Nada de esto escribe en ninguna base. La métrica de la compartida sigue en
`null`, que es la verdad hasta que revise alguien calificado.

EL CAMINO, TAL COMO ESTÁ CONSTRUIDO

    GET  /review                 → la bandeja de casos pendientes
    POST /review/{decision_id}   → veredicto: crea fila HUMAN_VALIDATED que
                                   COMPARTE product_dna_id con la original
    GET  /metrics/classification → empareja las dos por product_dna_id y
                                   produce el porcentaje

No hace falta endpoint nuevo: `review.py` ya lo hace y duplicarlo sería peor.
Lo que faltaba era la prueba de que la cadena entera cierra.

LO QUE ESTE CAMINO TODAVÍA NO PUEDE HACER

Distinguir un veredicto del cliente de uno del propio equipo. Ver
`test_hoy_no_se_puede_saber_quien_emitio_un_veredicto`. El campo lo aprueba
Persona 1: toca el Canonical Model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import ClassificationDecision
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 9, 10, 0, tzinfo=UTC)
DNA = uuid.uuid4()

#: Quién revisa cuando el veredicto viene de fuera. Hoy sólo llega al texto de
#: `reasoning`; ver el hueco declarado al final del archivo.
REVISOR_EXTERNO = "externo/revisor-1"


def _decision_maquina(*, fraccion: str | None, minutos: int = 0) -> ClassificationDecision:
    """Lo que el motor concluyó, esperando a que alguien lo mire."""
    d = ClassificationDecision(
        product_dna_id=DNA,
        trade_flow="IMPORT",
        operation_date=date(2024, 3, 15),
        status="HUMAN_REVIEW_REQUIRED",
        subheading=fraccion[:6] if fraccion else None,
        fraction_code=fraccion,
        data_origin="SYNTHETIC",
        requires_human_review=True,
    )
    d.id = uuid.uuid4()
    d.created_at = AHORA + timedelta(minutes=minutos)
    d.updated_at = d.created_at
    d.rgi_path = ["RGI-1", "RGI-3c"]
    d.rgi_trace = []
    d.legal_rule_ids = []
    d.input_snapshot = {}
    d.missing_information = []
    return d


class SesionFalsa:
    """Sesión mínima que sostiene el camino entero.

    `add`/`flush` acumulan en la misma lista que leen las consultas, que es lo
    que permite que un veredicto escrito por `revisar()` lo vea después
    `precision()` sin pasar por Postgres.
    """

    def __init__(self, filas: list[ClassificationDecision]) -> None:
        self.filas = filas

    def get(self, _modelo: type, id_: uuid.UUID, **_opciones: Any) -> Any:
        return next((f for f in self.filas if f.id == id_), None)

    def add(self, fila: Any) -> None:
        if fila.id is None:
            fila.id = uuid.uuid4()
        fila.created_at = fila.created_at or AHORA + timedelta(hours=1)
        fila.updated_at = fila.created_at
        self.filas.append(fila)

    def flush(self) -> None:
        return None

    def scalar(self, sentencia: Any) -> Any:
        """«¿Hay un veredicto que apunte a esta decisión?» — la única escalar."""
        objetivo = [v for v in sentencia.compile().params.values() if isinstance(v, uuid.UUID)]
        return next(
            (
                f.id
                for f in self.filas
                if f.data_origin == "HUMAN_VALIDATED" and f.reviews_decision_id in objetivo
            ),
            None,
        )

    def rollback(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def scalars(self, sentencia: Any) -> Any:
        # Sólo el WHERE: `str(select(Modelo))` lista TODAS las columnas en el
        # SELECT, así que buscar «requires_human_review» en la sentencia
        # entera daba positivo hasta en las consultas que no lo filtran.
        sql = str(sentencia)
        condicion = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
        humano = "!=" not in condicion
        pendientes = "requires_human_review" in condicion
        r = type("R", (), {})()

        def _filtrar() -> list[ClassificationDecision]:
            filas = [f for f in self.filas if (f.data_origin == "HUMAN_VALIDATED") is humano]
            if pendientes:
                filas = [f for f in filas if f.requires_human_review]
            return sorted(filas, key=lambda f: f.created_at)

        r.all = _filtrar
        return r


def _cliente(filas: list[ClassificationDecision]) -> tuple[TestClient, SesionFalsa]:
    sesion = SesionFalsa(filas)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: sesion
    return TestClient(app), sesion


# ── El camino completo ───────────────────────────────────────────────────────


def test_un_veredicto_externo_produce_un_numero_real() -> None:
    """EL TEST QUE PEDÍA PERSONA 1.

    Antes de que llegue el primer pedimento del cliente ya consta que la cadena
    cierra: bandeja → veredicto → porcentaje.
    """
    decision = _decision_maquina(fraccion="85285900")
    cliente, _ = _cliente([decision])

    with cliente as c:
        antes = c.get("/metrics/classification").json()
        assert antes["fraction_accuracy"]["porcentaje"] is None, "desconocida, no cero"

        # El revisor externo corrige: no era un monitor, era una computadora.
        respuesta = c.post(
            f"/review/{decision.id}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": REVISOR_EXTERNO,
                "fraction_code": "84713001",
                "nota": "Es una computadora portátil, no un monitor.",
            },
        )
        assert respuesta.status_code == 201, respuesta.text

        despues = c.get("/metrics/classification").json()

    assert despues["fraction_accuracy"]["comparados"] == 1
    assert despues["fraction_accuracy"]["porcentaje"] is not None, (
        "con un veredicto emparejado, la precisión deja de ser desconocida"
    )
    assert despues["corregidas"] == 1


def test_confirmar_tambien_mide_y_sube_el_acierto() -> None:
    """Es la mitad que hace subir el porcentaje; sin ella sólo se vería lo malo."""
    decision = _decision_maquina(fraccion="84713001")
    cliente, _ = _cliente([decision])

    with cliente as c:
        c.post(
            f"/review/{decision.id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )
        m = c.get("/metrics/classification").json()

    assert m["fraction_accuracy"]["aciertos"] == 1
    assert m["fraction_accuracy"]["porcentaje"] == "100.00"
    assert m["confirmadas"] == 1


def test_el_veredicto_no_sobrescribe_la_decision_de_la_maquina() -> None:
    """Medir exige conservar las dos respuestas.

    Si la revisión editara la decisión original, el numerador de la métrica
    desaparecería — y con él la única forma de saber si el motor mejora.
    """
    decision = _decision_maquina(fraccion="85285900")
    cliente, sesion = _cliente([decision])

    with cliente as c:
        c.post(
            f"/review/{decision.id}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": REVISOR_EXTERNO,
                "fraction_code": "84713001",
            },
        )

    assert decision.fraction_code == "85285900", "la máquina dijo lo que dijo"
    assert decision.data_origin == "SYNTHETIC"
    assert len(sesion.filas) == 2, "la humana se añade, no reemplaza"


def test_el_caso_revisado_sale_de_la_bandeja() -> None:
    decision = _decision_maquina(fraccion="85285900")
    cliente, _ = _cliente([decision])

    with cliente as c:
        assert len(c.get("/review").json()) == 1
        c.post(
            f"/review/{decision.id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )
        assert c.get("/review").json() == []


def test_la_revision_no_vuelve_a_la_bandeja() -> None:
    """Una fila `HUMAN_VALIDATED` no se revisa: ya es el veredicto."""
    decision = _decision_maquina(fraccion="85285900")
    cliente, sesion = _cliente([decision])

    with cliente as c:
        r = c.post(
            f"/review/{decision.id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )
        humana_id = r.json()["revision_id"]
        segunda = c.post(
            f"/review/{humana_id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )

    assert segunda.status_code == 409
    assert len(sesion.filas) == 2


def test_corregir_sin_fraccion_se_rechaza() -> None:
    """«El motor se equivocó» sin decir en qué no sirve para medir nada."""
    decision = _decision_maquina(fraccion="85285900")
    cliente, _ = _cliente([decision])

    with cliente as c:
        r = c.post(
            f"/review/{decision.id}",
            json={"veredicto": "CORRIGE", "reviewer": REVISOR_EXTERNO},
        )

    assert r.status_code == 422


def test_un_veredicto_anonimo_se_rechaza() -> None:
    """Una corrección sin autor no es auditable, venga de dentro o de fuera."""
    decision = _decision_maquina(fraccion="85285900")
    cliente, _ = _cliente([decision])

    with cliente as c:
        r = c.post(f"/review/{decision.id}", json={"veredicto": "CONFIRMA", "reviewer": ""})

    assert r.status_code == 422


# ── El hueco declarado ───────────────────────────────────────────────────────


def test_hoy_no_se_puede_saber_quien_emitio_un_veredicto() -> None:
    """HUECO DECLARADO, no un fallo de este PR.

    `reviewer` viaja en la petición y acaba dentro del texto libre de
    `reasoning`. No hay columna, así que la métrica —que empareja por
    `data_origin = HUMAN_VALIDATED` y nada más— no puede separar un veredicto
    del cliente de uno del propio equipo. Y medir el sistema con los veredictos de
    quien lo construyó lo mide contra sus propias suposiciones.

    Este test NO pide que se arregle aquí: fija el hueco para que se vea, y
    falla el día que alguien añada la columna sin actualizar la métrica.
    """
    decision = _decision_maquina(fraccion="85285900")
    cliente, sesion = _cliente([decision])

    with cliente as c:
        c.post(
            f"/review/{decision.id}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": REVISOR_EXTERNO,
                "fraction_code": "84713001",
            },
        )

    humana = next(f for f in sesion.filas if f.data_origin == "HUMAN_VALIDATED")

    columnas = {c.name for c in ClassificationDecision.__table__.columns}
    assert "reviewer" not in columnas, (
        "si ya existe la columna, la métrica tiene que poder filtrar por ella: "
        "actualiza este test y metrics.py a la vez"
    )
    # Lo único que queda del revisor es texto libre dentro del razonamiento.
    assert REVISOR_EXTERNO in (humana.reasoning or "")


# ── Un caso se revisa una sola vez (Persona 1, 14-sep) ───────────────────────


def test_un_caso_ya_revisado_no_admite_un_segundo_veredicto() -> None:
    """EL HUECO QUE VERIFICÓ PERSONA 1.

    El único 409 impedía «revisar una revisión». Un segundo POST sobre la
    decisión de MÁQUINA ya revisada creaba otro HUMAN_VALIDATED y la métrica
    contaba dos veces el mismo caso.
    """
    decision = _decision_maquina(fraccion="85285900")
    cliente, sesion = _cliente([decision])

    with cliente as c:
        primero = c.post(
            f"/review/{decision.id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )
        segundo = c.post(
            f"/review/{decision.id}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": "otro.revisor",
                "fraction_code": "84713001",
            },
        )
        m = c.get("/metrics/classification").json()

    assert primero.status_code == 201
    assert segundo.status_code == 409
    humanos = [f for f in sesion.filas if f.data_origin == "HUMAN_VALIDATED"]
    assert len(humanos) == 1, "el segundo no escribió nada"
    assert m["revisadas"] == 1
    assert m["fraction_accuracy"]["comparados"] == 1


def test_la_tasa_de_revision_humana_no_pasa_del_cien_por_ciento() -> None:
    """Con el hueco abierto, revisar dos veces el único caso daba 200 %."""
    decision = _decision_maquina(fraccion="85285900")
    cliente, _ = _cliente([decision])

    with cliente as c:
        for _ in range(3):
            c.post(
                f"/review/{decision.id}",
                json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
            )
        tasa = c.get("/metrics/classification").json()["human_review_rate"]

    assert tasa == "100.00"


def test_la_original_se_lee_bloqueada_para_escribir() -> None:
    """Sin FOR UPDATE, dos POST simultáneos leerían los dos «pendiente»."""
    decision = _decision_maquina(fraccion="85285900")
    cliente, sesion = _cliente([decision])
    opciones: list[dict[str, Any]] = []
    get_real = sesion.get

    def espia(modelo: type, id_: uuid.UUID, **kw: Any) -> Any:
        opciones.append(kw)
        return get_real(modelo, id_, **kw)

    sesion.get = espia  # type: ignore[method-assign]
    with cliente as c:
        c.post(
            f"/review/{decision.id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )

    assert opciones and opciones[0].get("with_for_update") is True


def _escenario_real() -> tuple[
    ClassificationDecision, ClassificationDecision, ClassificationDecision
]:
    """Lo que hay en la compartida: UN DNA, tres fechas de operación.

    Cada decisión propone una fracción distinta para que, si el emparejamiento
    se equivoca de decisión, el conteo de confirmadas y corregidas lo delate.
    """
    caso_2024 = _decision_maquina(fraccion="84713001", minutos=0)
    caso_2024.operation_date = date(2024, 3, 15)
    caso_2026_ene = _decision_maquina(fraccion="85285900", minutos=5)
    caso_2026_ene.operation_date = date(2026, 1, 15)
    caso_2026_mar = _decision_maquina(fraccion="85176201", minutos=10)
    caso_2026_mar.operation_date = date(2026, 3, 15)
    return caso_2024, caso_2026_ene, caso_2026_mar


def test_un_veredicto_sobre_2024_se_empareja_con_la_decision_de_2024() -> None:
    """EL HUECO QUE FIJABA EL #79, AL REVÉS.

    Con la heurística de DNA + tiempo este veredicto se comparaba contra el
    caso de 2026-03-15, que es la decisión más reciente del DNA: otra tarifa
    vigente, otro caso. Ahora se compara contra la de 2024, que es la que
    revisó. Confirmar 84713001 frente a 85176201 habría salido «corregida».
    """
    caso_2024, caso_2026_ene, caso_2026_mar = _escenario_real()
    cliente, _ = _cliente([caso_2024, caso_2026_ene, caso_2026_mar])

    with cliente as c:
        r = c.post(
            f"/review/{caso_2024.id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )
        m = c.get("/metrics/classification").json()

    assert r.status_code == 201
    assert m["confirmadas"] == 1
    assert m["corregidas"] == 0
    assert m["fraction_accuracy"]["aciertos"] == 1


def test_dos_veredictos_de_casos_distintos_del_mismo_dna_van_cada_uno_a_su_decision() -> None:
    """Antes los dos se emparejaban con la misma decisión y se contaba dos veces."""
    caso_2024, caso_2026_ene, caso_2026_mar = _escenario_real()
    cliente, _ = _cliente([caso_2024, caso_2026_ene, caso_2026_mar])

    with cliente as c:
        c.post(
            f"/review/{caso_2024.id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )
        c.post(
            f"/review/{caso_2026_mar.id}",
            json={
                "veredicto": "CORRIGE",
                "reviewer": REVISOR_EXTERNO,
                "fraction_code": "84713001",
            },
        )
        m = c.get("/metrics/classification").json()

    assert m["revisadas"] == 2
    assert m["confirmadas"] == 1, "el de 2024 confirmó su propia decisión"
    assert m["corregidas"] == 1, "el de 2026-03 corrigió la suya"
    assert m["fraction_accuracy"]["comparados"] == 2
    assert m["fraction_accuracy"]["aciertos"] == 1


def test_un_segundo_veredicto_sobre_la_misma_decision_da_409_por_la_aplicacion() -> None:
    """La capa de aplicación. La de la base (UNIQUE) se prueba contra Postgres
    en `test_reviews_decision_id_integracion.py`."""
    caso_2024, caso_2026_ene, caso_2026_mar = _escenario_real()
    cliente, sesion = _cliente([caso_2024, caso_2026_ene, caso_2026_mar])

    with cliente as c:
        primero = c.post(
            f"/review/{caso_2024.id}",
            json={"veredicto": "CONFIRMA", "reviewer": REVISOR_EXTERNO},
        )
        segundo = c.post(
            f"/review/{caso_2024.id}",
            json={"veredicto": "CORRIGE", "reviewer": "otro", "fraction_code": "85285900"},
        )

    assert (primero.status_code, segundo.status_code) == (201, 409)
    assert sum(1 for f in sesion.filas if f.data_origin == "HUMAN_VALIDATED") == 1
