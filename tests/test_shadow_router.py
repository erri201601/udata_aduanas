"""Tests de `GET /pedimentos/{id}/shadow`.

LA CONFUSIÓN QUE ESTA PANTALLA EXISTE PARA IMPEDIR

«Cero hallazgos» y «no pude revisarlo» se ven igual en cualquier tabla que no
los separe, y alguien puede presentar ante la autoridad un pedimento sin
revisar creyendo que pasó el filtro. Los tests que importan son los que
impiden que una partida sin comprobar acabe contada como conforme.

El otro test que importa es el del contrato con el motor: los motivos de
no-verificación se parsean de la cadena que escribe `core/shadow/compare.py`.
Se comprueba contra el motor DE VERDAD, no contra una cadena a mano — si
alguien cambia el formato ahí, este test falla en vez de que los motivos
dejen de atribuirse en silencio.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import Pedimento, PedimentoItem, RiskFinding, ShadowReview
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

PEDIMENTO_ID = uuid.UUID("49df3c21-3de0-48d9-8380-73b539206a03")
PARTIDA_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
REVISION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
AHORA = datetime(2026, 9, 8, 13, 20, tzinfo=UTC)


def _pedimento() -> Any:
    p = Pedimento(
        client_id=uuid.uuid4(),
        pedimento_number="26  47  3801  6000123",
        customs_office="470",
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        data_origin="SYNTHETIC",
        is_simulation=True,
    )
    p.id = PEDIMENTO_ID
    return p


def _partida(**kwargs: Any) -> Any:
    campos: dict[str, Any] = {
        "pedimento_id": PEDIMENTO_ID,
        "line_number": 1,
        "description": 'Laptop Demo 14" 8GB',
        "declared_fraction_code": "84714902",
        "declared_nico_code": "00",
        "country_of_origin": "CN",
        "customs_value": Decimal("1575000.00"),
        "customs_value_currency": "MXN",
        "quantity": Decimal("1"),
        "data_origin": "SYNTHETIC",
    }
    campos.update(kwargs)
    item = PedimentoItem(**campos)
    item.id = PARTIDA_ID
    return item


def _revision(
    *, unverifiable: list[str], is_complete: bool = False, verified: list[str] | None = None
) -> Any:
    r = ShadowReview(
        pedimento_id=PEDIMENTO_ID,
        is_complete=is_complete,
        unverifiable=unverifiable,
        verified=verified or [],
        engine_version="review-1.0",
        data_origin="SYNTHETIC",
    )
    r.id = REVISION_ID
    r.created_at = AHORA
    return r


def _hallazgo(**kwargs: Any) -> Any:
    campos: dict[str, Any] = {
        "pedimento_id": PEDIMENTO_ID,
        "pedimento_item_id": PARTIDA_ID,
        "shadow_review_id": REVISION_ID,
        "finding_type": "FRACTION_MISMATCH",
        "field": "fraction_code",
        "declared_value": "84714902",
        "expected_value": "84713001",
        "severity": "CRITICAL",
        "data_origin": "SYNTHETIC",
        "is_simulation": True,
    }
    campos.update(kwargs)
    h = RiskFinding(**campos)
    h.id = uuid.uuid4()
    return h


class SesionFalsa:
    """Devuelve el pedimento, sus partidas, la revisión y los hallazgos."""

    def __init__(
        self,
        *,
        pedimento: Any = None,
        partidas: list[Any] | None = None,
        revision: Any = None,
        hallazgos: list[Any] | None = None,
        total_revisiones: int = 1,
    ) -> None:
        self._pedimento = pedimento
        self._partidas = partidas or []
        self._revision = revision
        self._hallazgos = hallazgos or []
        self._total = total_revisiones
        self._scalars = 0

    def get(self, _modelo: Any, _id: Any) -> Any:
        return self._pedimento

    def scalar(self, _sentencia: Any) -> Any:
        return self._total

    def scalars(self, _sentencia: Any) -> Any:
        # El router consulta en orden fijo: partidas, revisión, hallazgos.
        self._scalars += 1
        lote = {
            1: self._partidas,
            2: [self._revision] if self._revision else [],
            3: self._hallazgos,
        }[self._scalars]
        return type(
            "R",
            (),
            {"all": lambda _s, _l=lote: _l, "first": lambda _s, _l=lote: _l[0] if _l else None},
        )()


def _cliente(**kwargs: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(**kwargs)
    return TestClient(app)


@pytest.fixture
def sin_verificar() -> Iterator[TestClient]:
    """El caso real de la base: revisado dos veces, nada comprobable."""
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(
            unverifiable=[
                "línea 1: la clasificación no llegó a ser defendible, no se puede afirmar "
                "que lo declarado sea incorrecto",
                "línea 1: no se conoce qué NOM exige la fracción esperada",
            ]
        ),
        hallazgos=[],
        total_revisiones=2,
    ) as c:
        yield c


def test_el_espejo_responde(sin_verificar: TestClient) -> None:
    assert sin_verificar.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").status_code == 200


def test_un_pedimento_que_no_existe_da_404() -> None:
    with _cliente(pedimento=None) as c:
        assert c.get(f"/pedimentos/{uuid.uuid4()}/shadow").status_code == 404


def test_sin_hallazgos_no_es_conforme(sin_verificar: TestClient) -> None:
    """EL TEST QUE IMPORTA.

    Una partida sin hallazgos que no se pudo comprobar NO se cuenta como
    conforme. Si se contara, alguien presentaría un pedimento sin revisar
    creyendo que pasó el filtro.
    """
    d = sin_verificar.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["conformes"] == 0
    assert d["sin_verificar"] == 1
    assert d["divergentes"] == 0
    assert d["lineas"][0]["estado"] == "SIN_VERIFICAR"


def test_cada_motivo_se_cuelga_de_su_partida(sin_verificar: TestClient) -> None:
    d = sin_verificar.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert len(d["lineas"][0]["no_verificable_por"]) == 2
    # El prefijo «línea 1: » se quita: ya se sabe de qué partida es.
    assert not d["lineas"][0]["no_verificable_por"][0].startswith("línea")
    assert d["motivos_sin_atribuir"] == []


def test_una_partida_conforme_no_repite_la_fraccion_declarada() -> None:
    """Decir «esperado: lo mismo» fabricaría una confirmación que nadie emitió."""
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[], is_complete=True),
        hallazgos=[],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["lineas"][0]["estado"] == "CONFORME"
    assert d["lineas"][0]["expected_fraction_code"] is None
    assert d["conformes"] == 1


def test_una_divergencia_enseña_las_dos_caras() -> None:
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[]),
        hallazgos=[_hallazgo()],
    ) as c:
        linea = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()["lineas"][0]

    assert linea["estado"] == "DIVERGENTE"
    assert linea["declared_fraction_code"] == "84714902"
    assert linea["expected_fraction_code"] == "84713001"
    assert linea["peor_severidad"] == "CRITICAL"


def test_hallazgo_y_hueco_a_la_vez_es_verificacion_parcial() -> None:
    """Presentarla como revisada sería exacto en un campo y falso en el conjunto."""
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=["línea 1: no se conoce qué NOM exige la fracción"]),
        hallazgos=[_hallazgo()],
    ) as c:
        linea = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()["lineas"][0]

    assert linea["estado"] == "DIVERGENTE"
    assert linea["verificacion_parcial"] is True
    assert linea["no_verificable_por"] != []


def test_un_hallazgo_sin_monto_no_se_estima_en_cero() -> None:
    """Una NOM faltante no cambia lo que se paga y aun así detiene la mercancía."""
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[]),
        hallazgos=[_hallazgo(finding_type="MISSING_NOM", field="nom", impact_amount=None)],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["exposicion_cuantificada"] is None
    assert d["hallazgos_sin_monto"] == 1


def test_no_se_suman_monedas_distintas() -> None:
    """Sumar pesos con dólares da un número que parece dinero y no lo es."""
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[]),
        hallazgos=[
            _hallazgo(impact_amount=Decimal("100"), impact_amount_currency="MXN"),
            _hallazgo(impact_amount=Decimal("50"), impact_amount_currency="USD"),
        ],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["monedas_mezcladas"] is True
    assert d["exposicion_cuantificada"] is None
    assert d["exposicion_moneda"] is None


def test_nunca_auditado_no_es_auditado_sin_hallazgos() -> None:
    """Tres estados, no dos: sin revisión no hay veredicto que dar."""
    with _cliente(
        pedimento=_pedimento(), partidas=[_partida()], revision=None, total_revisiones=0
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["revision"] is None
    assert d["revisiones_totales"] == 0
    assert d["conformes"] == 0


def test_el_formato_del_motor_es_el_que_se_parsea() -> None:
    """EL CONTRATO CON `core/shadow/compare.py`.

    Los motivos se parsean de la cadena que escribe el motor. Se comprueba
    contra el motor de verdad: si alguien cambia el formato allí, esto falla
    en vez de que los motivos dejen de atribuirse en silencio.
    """
    from apps.api.routers.shadow import _repartir_motivos
    from core.shadow import DeclaredItem, ExpectedItem
    from core.shadow.compare import compare

    comparacion = compare(
        [DeclaredItem(line_number=7, fraction_code="84714902")],
        [ExpectedItem(line_number=7, fraction_code="84713001", is_resolved=False)],
    )
    assert comparacion.unverifiable, "el motor debería reportar motivos aquí"

    por_linea, sueltos = _repartir_motivos(list(comparacion.unverifiable))

    assert sueltos == [], f"el formato del motor cambió: {sueltos}"
    assert 7 in por_linea


def test_las_columnas_usadas_existen() -> None:
    """Evita asumir columnas, que ya me costó una vez."""
    assert {"shadow_review_id", "pedimento_item_id", "field", "expected_value"} <= {
        c.name for c in RiskFinding.__table__.columns
    }
    assert {"is_complete", "unverifiable", "engine_version"} <= {
        c.name for c in ShadowReview.__table__.columns
    }
    assert {"line_number", "declared_fraction_code"} <= {
        c.name for c in PedimentoItem.__table__.columns
    }


# ── El mismo dinero no se cuenta dos veces (22-sep) ─────────────────────────


def test_dos_hallazgos_de_la_misma_partida_no_duplican_el_dinero() -> None:
    """EL TEST QUE IMPORTA.

    El motor atribuye el monto ENTERO a cada divergencia cuantificable a
    propósito: cada causa explica la misma diferencia por completo. Sumarlos
    fila por fila enseñaría el doble del dinero que existe — y con el corpus,
    una partida puede traer divergencia de valor y de origen a la vez.
    """
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[]),
        hallazgos=[
            _hallazgo(impact_amount=Decimal("14520.95"), impact_amount_currency="MXN"),
            _hallazgo(
                finding_type="ORIGIN_MISMATCH",
                field="country_of_origin",
                impact_amount=Decimal("14520.95"),
                impact_amount_currency="MXN",
            ),
        ],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["exposicion_cuantificada"] == "14520.95", "un monto por partida"
    assert len(d["lineas"][0]["divergencias"]) == 2, "pero los dos hallazgos se enseñan"


def test_partidas_distintas_si_suman() -> None:
    """Lo que no se duplica dentro de una partida, entre partidas sí se suma."""
    otra = uuid.UUID("33333333-3333-3333-3333-333333333333")
    partida_2 = _partida(line_number=2)
    partida_2.id = otra

    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida(), partida_2],
        revision=_revision(unverifiable=[]),
        hallazgos=[
            _hallazgo(impact_amount=Decimal("100.00"), impact_amount_currency="MXN"),
            _hallazgo(
                pedimento_item_id=otra,
                impact_amount=Decimal("50.00"),
                impact_amount_currency="MXN",
            ),
        ],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["exposicion_cuantificada"] == "150.00"


# ── PARCIAL tiene su contador (Persona 1, 5-oct) ───────────────────────────


def test_una_partida_parcial_cuenta_como_comprobada() -> None:
    """PARCIAL existía en la línea y no lo contaba ningún total.

    Los cuatro contadores no sumaban `partidas`, y la consola —que calculaba
    «comprobadas» como divergentes + conformes— daba cero sobre un pedimento
    donde cada partida enseñaba nueve de diez comprobaciones hechas. El cartel
    rojo de «no se pudo comprobar nada» volvía a salir encima de la pantalla
    que acababa de enumerar lo comprobado.

    Séptima vez en este proyecto que dos estados se colapsan o que un estado
    se queda sin su rama.
    """
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(
            unverifiable=["línea 1: no se conoce qué NOM exige la fracción esperada"],
            verified=["línea 1: fracción arancelaria", "línea 1: valor en aduana"],
        ),
        hallazgos=[],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["lineas"][0]["estado"] == "PARCIAL"
    assert d["parciales"] == 1, "PARCIAL tiene que tener su contador"
    assert d["sin_verificar"] == 0, "se comprobó algo: no es «sin verificar»"
    assert d["conformes"] == 0, "y le falta algo: tampoco es conforme"
    suma = d["divergentes"] + d["parciales"] + d["sin_verificar"] + d["conformes"]
    assert suma == d["partidas"], "los estados tienen que sumar las partidas"


def test_una_partida_parcial_dice_que_comprobo() -> None:
    """La mitad que faltaba: lo que SÍ se comprobó, por nombre."""
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(
            unverifiable=["línea 1: no se conoce qué NOM exige la fracción esperada"],
            verified=["línea 1: fracción arancelaria", "línea 1: valor en aduana"],
        ),
        hallazgos=[],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["lineas"][0]["comprobado"] == ["fracción arancelaria", "valor en aduana"]


def test_el_denominador_sale_del_motor_no_de_la_pantalla() -> None:
    """«9 de 10» sólo significa algo si el 10 sale de la misma lista que el 9.

    Con el total escrito a mano en la consola, añadir una comprobación al
    motor dejaría la pantalla diciendo «10 de 10» sobre una partida a la que
    le falta una.
    """
    from core.shadow import comprobaciones_posibles

    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[], verified=["línea 1: fracción arancelaria"]),
        hallazgos=[],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["comprobaciones_posibles"] == list(comprobaciones_posibles())
    assert "fracción arancelaria" in d["comprobaciones_posibles"], (
        "el nombre que viaja en `comprobado` tiene que estar en la lista, "
        "o la pantalla no puede restar los que faltan"
    )


def test_una_revision_vieja_sin_comprobaciones_se_sigue_leyendo() -> None:
    """Las corridas anteriores a la columna no la tienen.

    Tienen que seguir leyéndose, y sin comprobaciones registradas: ésa es la
    verdad sobre ellas, no un cero que haya que esconder.
    """
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=["línea 1: no se consultó la ficha técnica"]),
        hallazgos=[],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["lineas"][0]["comprobado"] == []
    assert d["lineas"][0]["estado"] == "SIN_VERIFICAR", (
        "sin comprobaciones registradas no se puede llamar parcial"
    )


def test_los_nombres_que_escribe_el_motor_son_los_de_la_lista() -> None:
    """EL OTRO CONTRATO CON `core/shadow/compare.py`.

    La consola resta `comprobado` de `comprobaciones_posibles` para nombrar lo
    que falta. Eso sólo es correcto si los nombres son LOS MISMOS: si el motor
    escribiera «fracción» donde la lista dice «fracción arancelaria», la
    pantalla diría que no se comprobó la fracción justo después de enseñarla
    como comprobada.

    Se comprueba contra el motor de verdad, igual que el formato de los
    motivos, y no contra una cadena escrita a mano.
    """
    from apps.api.routers.shadow import _repartir_motivos
    from core.shadow import DeclaredItem, ExpectedItem, comprobaciones_posibles
    from core.shadow.compare import compare

    comparacion = compare(
        [DeclaredItem(line_number=7, fraction_code="84714902", country_of_origin="CN")],
        [
            ExpectedItem(
                line_number=7,
                fraction_code="84713001",
                is_resolved=True,
                country_of_origin="CN",
            )
        ],
    )
    assert comparacion.verified, "el motor debería reportar comprobaciones aquí"

    por_linea, sueltos = _repartir_motivos(list(comparacion.verified))

    assert sueltos == [], f"el formato del motor cambió: {sueltos}"
    posibles = set(comprobaciones_posibles())
    desconocidos = [n for n in por_linea[7] if n not in posibles]
    assert desconocidos == [], (
        f"el motor escribe nombres que no están en la lista: {desconocidos}. "
        "La pantalla los contaría como no comprobados."
    )


# ── Un sobrepago no resta de la exposición (Persona 1, 5-oct) ──────────────


def test_un_sobrepago_no_resta_de_la_exposicion() -> None:
    """El pedimento 600012 enseñaba «exposición cuantificada» en negativo.

    Un importe con un signo menos delante, en el sitio donde la pantalla dice
    cuánto hay en juego. No es exposición: es dinero que se pagó de más, y
    mezclar las dos direcciones da un neto que no se puede presentar ni como
    adeudo ni como recuperable.
    """
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[]),
        hallazgos=[_hallazgo(impact_amount=Decimal("-29674.51"))],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert d["exposicion_cuantificada"] is None, "un sobrepago no es exposición"
    assert d["sobrepagos"] == 1, "y no puede desaparecer sin decirlo"


def test_un_adeudo_y_un_sobrepago_no_se_netean() -> None:
    """50 000 que se deben y 30 000 pagados de más no son 20 000 de nada."""
    otra = uuid.uuid4()
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[]),
        hallazgos=[
            _hallazgo(impact_amount=Decimal("50000.00")),
            _hallazgo(pedimento_item_id=otra, impact_amount=Decimal("-30000.00")),
        ],
    ) as c:
        d = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()

    assert Decimal(d["exposicion_cuantificada"]) == Decimal("50000.00"), (
        "la exposición es lo que se debe, sin descontar lo que se pagó de más"
    )
    assert d["sobrepagos"] == 1


def test_la_cara_esperada_lee_lo_que_el_comparador_escribe() -> None:
    """El contrato contra el comparador de verdad, no contra un fixture.

    La pantalla buscaba la fracción esperada en el campo `"tariff_fraction"` y
    el comparador escribe `"fraction_code"`: la cara «esperado» no enseñó nunca
    una fracción. Este test pasaba igual, porque su fixture escribía a mano el
    nombre equivocado (7-oct).
    """
    from core.shadow.compare import compare
    from core.shadow.divergences import DivergenceType

    from tests.test_pedimento_shadow import declarado, esperado

    divergencia = next(
        d
        for d in compare([declarado(fraction_code="84714902")], [esperado()]).divergences
        if d.kind is DivergenceType.FRACTION_MISMATCH
    )
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[]),
        hallazgos=[
            _hallazgo(
                finding_type=divergencia.kind.value,
                field=divergencia.field,
                declared_value=divergencia.declared_value,
                expected_value=divergencia.expected_value,
            )
        ],
    ) as c:
        linea = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()["lineas"][0]

    assert linea["expected_fraction_code"] == "84713001"


# ── Coincidir también es un resultado (7-oct) ──────────────────────────────


def test_una_fraccion_comprobada_que_coincide_se_dice() -> None:
    """La caja decía «no se construyó una expectativa» encima de la etiqueta
    verde «fracción arancelaria»: en 11 de las 12 partidas del 600015."""
    from core.shadow.compare import COMPROBACION_DE_FRACCION

    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[], verified=[f"línea 1: {COMPROBACION_DE_FRACCION}"]),
        hallazgos=[],
    ) as c:
        linea = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()["lineas"][0]

    assert linea["fraccion_coincide"] is True
    assert linea["expected_fraction_code"] == linea["declared_fraction_code"]


def test_si_difiere_no_se_dice_que_coincide() -> None:
    from core.shadow.compare import COMPROBACION_DE_FRACCION

    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[], verified=[f"línea 1: {COMPROBACION_DE_FRACCION}"]),
        hallazgos=[_hallazgo()],
    ) as c:
        linea = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()["lineas"][0]

    assert linea["fraccion_coincide"] is False
    assert linea["expected_fraction_code"] == "84713001"


def test_sin_registro_de_la_comprobacion_no_se_afirma_nada() -> None:
    """El principio de siempre: sin constancia, no se rellena con lo declarado."""
    with _cliente(
        pedimento=_pedimento(),
        partidas=[_partida()],
        revision=_revision(unverifiable=[], verified=["línea 1: NICO"]),
        hallazgos=[],
    ) as c:
        linea = c.get(f"/pedimentos/{PEDIMENTO_ID}/shadow").json()["lineas"][0]

    assert linea["fraccion_coincide"] is False
    assert linea["expected_fraction_code"] is None
