"""El encadenado de los cuatro motores sobre un pedimento completo.

Lo que más se prueba aquí no es que sume bien, sino que se NIEGUE a sumar
cuando no debe: entre divisas distintas, sin tasas, y sin espejo.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from apps.api.routers.pedimentos import ReviewRequest
from core.review import LineInput, review_pedimento
from core.shadow import DeclaredItem, DivergenceType, ExpectedItem
from core.taxation import Money, TaxRates

TASAS_COMUNES = {"iva_rate": Decimal("0.16"), "dta_rate": Decimal("0.008")}


def linea(
    numero: int = 1,
    *,
    declarada: str = "85285900",
    esperada: str | None = "84713001",
    valor: str = "100000",
    divisa: str = "MXN",
    igi_declarada: str | None = "0.15",
    igi_esperada: str | None = "0.00",
    con_espejo: bool = True,
) -> LineInput:
    esperado = (
        ExpectedItem(
            line_number=numero,
            fraction_code=esperada,
            is_resolved=True,
            confidence=Decimal("1.0"),
            customs_value=Decimal(valor),
            customs_value_currency=divisa,
            required_nom_codes=(),
            required_identifiers=(),
        )
        if con_espejo
        else None
    )
    tasas = (
        (
            TaxRates(igi_rate=Decimal(igi_declarada), **TASAS_COMUNES),
            TaxRates(igi_rate=Decimal(igi_esperada), **TASAS_COMUNES),
        )
        if igi_declarada is not None and igi_esperada is not None
        else (None, None)
    )
    return LineInput(
        declared=DeclaredItem(
            line_number=numero,
            fraction_code=declarada,
            customs_value=Decimal(valor),
            customs_value_currency=divisa,
        ),
        expected=esperado,
        transaction_value=Money(amount=Decimal(valor), currency=divisa),
        declared_rates=tasas[0],
        expected_rates=tasas[1],
    )


# ── Lo que sí debe sumar ─────────────────────────────────────────────────────


def test_el_dinero_de_partidas_distintas_se_suma() -> None:
    """Dos mercancías distintas son dos diferencias distintas.

    Dentro de una partida los montos NO se suman —varias divergencias explican
    un mismo delta— pero entre partidas sí: es dinero separado.
    """
    r = review_pedimento(
        [
            linea(1, igi_declarada="0.00", igi_esperada="0.15"),
            linea(2, igi_declarada="0.00", igi_esperada="0.15"),
        ]
    )

    assert len(r.findings) == 2
    una_sola = review_pedimento([linea(1, igi_declarada="0.00", igi_esperada="0.15")])
    assert una_sola.total_exposure is not None
    assert r.total_exposure == una_sola.total_exposure * 2


def test_un_sobrepago_produce_una_oportunidad() -> None:
    """Pagar de más es recuperable, y el reverso del hallazgo es la oportunidad."""
    r = review_pedimento([linea(igi_declarada="0.20", igi_esperada="0.10")])

    assert r.total_recoverable is not None
    assert r.opportunities is not None
    assert r.opportunities.opportunities
    assert "ecuperable" in r.summary()


# ── Lo que el motor debe NEGARSE a hacer ─────────────────────────────────────


def test_no_suma_divisas_distintas() -> None:
    """Convertir exigiría elegir un tipo de cambio, y elegirlo mal cambia la
    cifra que se le lleva al cliente."""
    r = review_pedimento(
        [
            linea(1, divisa="MXN", igi_declarada="0.00", igi_esperada="0.15"),
            linea(2, divisa="USD", igi_declarada="0.00", igi_esperada="0.15"),
        ]
    )

    assert r.mixed_currencies
    assert r.total_exposure is None
    assert r.currency is None
    assert "divisas distintas" in r.summary()


def test_una_partida_sin_espejo_deja_el_pedimento_incompleto() -> None:
    """Sin expectativa no se compara, y sin comparar no se puede decir limpio."""
    r = review_pedimento([linea(1), linea(2, con_espejo=False)])

    assert not r.is_complete
    assert any("línea 2" in u for u in r.unverifiable)


def test_sin_tasas_hay_hallazgo_pero_no_monto() -> None:
    """Un riesgo de cumplimiento sigue siendo real aunque no se sepa cuánto
    cuesta. Inventar un cero daría una cifra plausible y falsa."""
    r = review_pedimento([linea(igi_declarada=None, igi_esperada=None)])

    assert r.findings
    assert r.findings[0].divergence.kind is DivergenceType.FRACTION_MISMATCH
    assert r.total_exposure is None
    assert "Sin cuantificar" in r.summary()


def test_un_pedimento_sin_partidas_no_se_declara_limpio() -> None:
    """Nada que revisar no es lo mismo que revisado y limpio."""
    r = review_pedimento([])

    assert not r.findings
    assert r.is_simulation


def test_una_simulacion_en_una_partida_contamina_el_informe() -> None:
    """§33: si parte de lo auditado es sintético, el todo no puede
    presentarse como real."""
    real = linea(1).model_copy(update={"is_simulation": False})
    sintetica = linea(2).model_copy(update={"is_simulation": True})

    assert review_pedimento([real, sintetica]).is_simulation
    assert not review_pedimento([real]).is_simulation


# ── De dónde sale el país esperado (Persona 1, 21-sep) ──────────────────────


class _SinCuotasCompensatorias:
    """`cuotas_vigentes()` siempre vacío: ninguna cuota cargada para esta
    combinación -- `compensatory_duty_applies` sale `None` ("no se sabe"),
    sin interferir con lo que estos tests sí verifican (país/NICO)."""

    def all(self) -> list[object]:
        return []


class _SesionConProveedor:
    """Sólo responde la consulta del país del proveedor (y, para que
    `_cuota_compensatoria_esperada` no truene, una lista vacía de cuotas)."""

    def __init__(self, pais: str | None) -> None:
        self.pais = pais
        self.consultas: list[str] = []

    def scalar(self, sentencia: object) -> object:
        self.consultas.append(str(sentencia))
        return self.pais

    def scalars(self, sentencia: object) -> _SinCuotasCompensatorias:
        return _SinCuotasCompensatorias()


def _partida(**kw: object) -> object:
    from database.models import PedimentoItem

    campos: dict[str, object] = {
        "line_number": 1,
        "description": "Tubo de acero",
        "declared_fraction_code": "73051291",
        "quantity": Decimal("10"),
        "country_of_origin": "BR",
        "data_origin": "SYNTHETIC",
        "invoice_item_id": uuid.uuid4(),
        "product_id": None,
    }
    campos.update(kw)
    return PedimentoItem(**campos)  # type: ignore[arg-type]


class _CatalogoFalso:
    def __init__(self, nicos: tuple[str, ...]) -> None:
        self._nicos = nicos
        self.consultas: list[str] = []

    def nicos(self, *, on_date: object, fraction_code: str) -> tuple[str, ...]:
        self.consultas.append(fraction_code)
        return self._nicos


def test_el_pais_se_busca_por_la_cadena_de_la_factura() -> None:
    """`Pedimento` no guarda proveedor: se llega por la factura."""
    from apps.api.routers.pedimentos import _pais_del_proveedor

    sesion = _SesionConProveedor("CN")
    pais = _pais_del_proveedor(sesion, _partida())  # type: ignore[arg-type]

    assert pais == "CN"
    sql = sesion.consultas[0]
    assert "suppliers" in sql and "invoices" in sql and "invoice_items" in sql


def test_sin_factura_ligada_no_se_consulta_ni_se_supone() -> None:
    from apps.api.routers.pedimentos import _pais_del_proveedor

    sesion = _SesionConProveedor("CN")
    pais = _pais_del_proveedor(sesion, _partida(invoice_item_id=None))  # type: ignore[arg-type]

    assert pais is None
    assert sesion.consultas == [], "ni siquiera se preguntó"


def test_una_partida_sin_producto_igual_se_le_comprueba_el_pais() -> None:
    """Sin producto no se puede clasificar, pero el origen SÍ se contrasta."""
    from apps.api.routers.pedimentos import _construir_espejo
    from core.shadow.types import ORIGEN_DEL_PROVEEDOR

    esperado = _construir_espejo(
        _SesionConProveedor("CN"),  # type: ignore[arg-type]
        _partida(product_id=None),  # type: ignore[arg-type]
        date(2026, 3, 15),
        _CatalogoFalso(("00",)),  # type: ignore[arg-type]
        ReviewRequest(),
    )

    assert esperado is not None
    assert esperado.country_of_origin == "CN"
    assert esperado.origin_source == ORIGEN_DEL_PROVEEDOR
    assert esperado.is_resolved is False, "no se clasificó nada"


# ── El NICO esperado ─────────────────────────────────────────────────────────


def test_una_fraccion_con_un_solo_nico_no_necesita_ficha_tecnica() -> None:
    """6 555 de las 8 135 fracciones vigentes tienen un único NICO.

    En esas no hay nada que elegir, y el Espejo puede esperarlo con la misma
    certeza con la que espera la fracción. Antes devolvía `None` en todas y las
    180 partidas del corpus arrastraban el mismo hueco —«saber si es el que
    corresponde exige la ficha técnica»— que para estas fracciones no era
    cierto: no hacía falta ninguna ficha, sólo mirar el catálogo.
    """
    from apps.api.routers.pedimentos import _nico_esperado

    catalogo = _CatalogoFalso(("00",))
    nico = _nico_esperado(catalogo, date(2026, 3, 15), "69111001")  # type: ignore[arg-type]

    assert nico == "00"
    assert catalogo.consultas == ["69111001"]


def test_con_varios_nico_no_se_elige_uno() -> None:
    """Elegir entre varios exige la ficha técnica: un NICO distingue por
    materia, uso o presentación.

    Suponerlo acusaría al pedimento de un NICO equivocado contra una
    expectativa inventada, que es peor que declarar el hueco. Misma disciplina
    que el descarte de la RGI 6: se resuelve sólo cuando queda uno.
    """
    from apps.api.routers.pedimentos import _nico_esperado

    nico = _nico_esperado(
        _CatalogoFalso(("01", "02", "99")),  # type: ignore[arg-type]
        date(2026, 3, 15),
        "73121001",
    )

    assert nico is None


def test_sin_fraccion_esperada_no_se_consulta_el_nico() -> None:
    """Si el motor no resolvió, no hay fracción de la que colgar un NICO.

    Y no se pregunta: consultar con `None` devolvería los NICO de nada.
    """
    from apps.api.routers.pedimentos import _nico_esperado

    catalogo = _CatalogoFalso(("00",))
    assert _nico_esperado(catalogo, date(2026, 3, 15), None) is None  # type: ignore[arg-type]
    assert catalogo.consultas == [], "ni siquiera se preguntó"


def test_una_fraccion_sin_nico_cargado_no_inventa_uno() -> None:
    """Catálogo vacío para esa fracción es un hueco nuestro, no un NICO."""
    from apps.api.routers.pedimentos import _nico_esperado

    assert (
        _nico_esperado(_CatalogoFalso(()), date(2026, 3, 15), "69111001")  # type: ignore[arg-type]
        is None
    )


def test_sin_producto_y_sin_proveedor_no_hay_espejo() -> None:
    from apps.api.routers.pedimentos import _construir_espejo

    assert (
        _construir_espejo(
            _SesionConProveedor(None),  # type: ignore[arg-type]
            _partida(  # type: ignore[arg-type]
                product_id=None,
                invoice_item_id=None,
                declared_fraction_code=None,
                price_paid=None,
                incrementables=None,
            ),
            date(2026, 3, 15),
            _CatalogoFalso(("00",)),  # type: ignore[arg-type]
            ReviewRequest(),
        )
        is None
    )


# ── El espejo documental: NICO y valor (Persona 1, 21-sep) ─────────────────


def test_el_valor_esperado_es_precio_pagado_mas_incrementables() -> None:
    from apps.api.routers.pedimentos import _valor_esperado

    valor, moneda = _valor_esperado(
        None,  # type: ignore[arg-type]  # MXN no toca la sesión -- retorna antes
        _partida(
            price_paid=Decimal("170000.00"),
            incrementables=Decimal("11511.88"),
            price_paid_currency="MXN",
            incrementables_currency="MXN",
        ),  # type: ignore[arg-type]
        date(2026, 1, 1),
    )

    assert valor == Decimal("181511.88")
    assert moneda == "MXN"


def test_sin_incrementables_no_se_supone_cero() -> None:
    """Cero es una afirmación. Aquí no consta."""
    from apps.api.routers.pedimentos import _valor_esperado

    valor, _ = _valor_esperado(
        None,  # type: ignore[arg-type]
        _partida(price_paid=Decimal("170000.00"), incrementables=None),  # type: ignore[arg-type]
        date(2026, 1, 1),
    )

    assert valor is None


def test_no_se_suman_divisas_distintas() -> None:
    from apps.api.routers.pedimentos import _valor_esperado

    valor, _ = _valor_esperado(
        None,  # type: ignore[arg-type]  # las divisas no coinciden -- retorna antes
        _partida(
            price_paid=Decimal("10000.00"),
            incrementables=Decimal("500.00"),
            price_paid_currency="USD",
            incrementables_currency="MXN",
        ),  # type: ignore[arg-type]
        date(2026, 1, 1),
    )

    assert valor is None


def test_el_espejo_documental_consulta_los_nico_de_la_fraccion_declarada() -> None:
    from apps.api.routers.pedimentos import _espejo_documental

    catalogo = _CatalogoFalso(("00", "01"))
    documental = _espejo_documental(
        _SesionConProveedor("CN"),  # type: ignore[arg-type]
        _partida(declared_fraction_code="73051291"),  # type: ignore[arg-type]
        date(2026, 3, 15),
        catalogo,  # type: ignore[arg-type]
        ReviewRequest(),
    )

    assert catalogo.consultas == ["73051291"], "se consulta la DECLARADA, no una esperada"
    assert documental["valid_nico_codes"] == ("00", "01")
    assert documental["country_of_origin"] == "CN"


def test_sin_fraccion_declarada_no_se_consulta_el_catalogo() -> None:
    from apps.api.routers.pedimentos import _espejo_documental

    catalogo = _CatalogoFalso(("00",))
    documental = _espejo_documental(
        _SesionConProveedor(None),  # type: ignore[arg-type]
        _partida(declared_fraction_code=None),  # type: ignore[arg-type]
        date(2026, 3, 15),
        catalogo,  # type: ignore[arg-type]
        ReviewRequest(),
    )

    assert catalogo.consultas == []
    assert documental["valid_nico_codes"] is None, "no se sabe, no es «ninguno»"
