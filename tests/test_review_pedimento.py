"""El encadenado de los cuatro motores sobre un pedimento completo.

Lo que más se prueba aquí no es que sume bien, sino que se NIEGUE a sumar
cuando no debe: entre divisas distintas, sin tasas, y sin espejo.
"""

from __future__ import annotations

from decimal import Decimal

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
