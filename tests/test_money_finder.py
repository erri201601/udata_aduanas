"""Tests del Money Finder.

En un motor de cálculo fiscal, un test que sólo comprueba el camino feliz no
sirve: el error que importa no es que reviente, es que devuelva un número
plausible y equivocado. Por eso la mitad de estos tests fijan cifras exactas
calculadas a mano.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.taxation import (
    CurrencyMismatchError,
    Money,
    TaxRates,
    compute_divergence,
    compute_taxes,
    customs_value,
)

pytestmark = pytest.mark.unit


def mxn(v: str) -> Money:
    return Money(amount=Decimal(v), currency="MXN")


TASAS = TaxRates(
    igi_rate=Decimal("0.15"),
    iva_rate=Decimal("0.16"),
    dta_rate=Decimal("0.008"),
    source_ids=("src-ligie-8471",),
)


# ── §22: nada de float ───────────────────────────────────────────────────────


def test_un_importe_no_se_construye_desde_float() -> None:
    """El error de precisión entra por aquí y no vuelve a salir.

    Decimal(0.1) ya vale 0.1000000000000000055511151231257827. En una cadena de
    contribuciones eso se acumula hasta producir un peso de diferencia, que en
    un pedimento es una discrepancia, no un redondeo.
    """
    with pytest.raises(TypeError, match="float"):
        Money(amount=0.1, currency="MXN")  # type: ignore[arg-type]


def test_una_tasa_no_puede_ser_float() -> None:
    with pytest.raises(TypeError, match="float"):
        mxn("100") * 0.16  # type: ignore[operator]


def test_una_tasa_mayor_que_uno_se_rechaza() -> None:
    """16 en vez de 0.16 es un error de dos órdenes de magnitud.

    Fallar ruidoso es mejor que calcular un IVA del 1600%: el segundo error se
    descubre semanas después, cuando alguien mira un total absurdo.
    """
    with pytest.raises(ValueError, match="fracción"):
        TaxRates(iva_rate=Decimal("16"))


def test_no_se_suman_divisas_distintas() -> None:
    """Sumar 100 USD y 100 MXN debe ser un error, no un 200 sin unidades."""
    with pytest.raises(CurrencyMismatchError):
        mxn("100") + Money(amount=Decimal("100"), currency="USD")


def test_la_conversion_exige_tipo_de_cambio_explicito() -> None:
    """Elegir el FIX de un día u otro cambia el resultado: no se supone."""
    usd = Money(amount=Decimal("1000.00"), currency="USD")

    convertido = usd.convert(to="MXN", rate=Decimal("17.1234"))

    assert convertido.currency == "MXN"
    assert convertido.amount == Decimal("17123.400000")


# ── Las cifras exactas ───────────────────────────────────────────────────────


def test_el_valor_en_aduana_suma_los_incrementables() -> None:
    """Omitirlos subvalúa la mercancía y arrastra el error a todo lo demás."""
    base, supuestos = customs_value(
        transaction_value=mxn("100000.00"),
        incrementables=[mxn("8000.00"), mxn("1500.00")],
    )

    assert base.amount == Decimal("109500.00")
    assert not supuestos


def test_sin_incrementables_se_declara_el_supuesto() -> None:
    """§36: lo que no se sabe se nombra, no se da por bueno en silencio."""
    _, supuestos = customs_value(transaction_value=mxn("100000.00"))

    assert supuestos
    assert "incrementables" in supuestos[0]


def test_las_contribuciones_dan_las_cifras_calculadas_a_mano() -> None:
    """Valor en aduana 100,000 MXN, IGI 15%, DTA 8 al millar, IVA 16%.

    IGI = 100000 * 0.15        = 15000.00
    DTA = 100000 * 0.008       =   800.00
    IVA = (100000+15000+800) * 0.16 = 18528.00
    total                      = 34328.00
    landed cost                = 134328.00
    """
    c = compute_taxes(transaction_value=mxn("100000.00"), rates=TASAS)

    assert c.item("IGI").amount.amount == Decimal("15000.00")  # type: ignore[union-attr]
    assert c.item("DTA").amount.amount == Decimal("800.00")  # type: ignore[union-attr]
    assert c.item("IVA").amount.amount == Decimal("18528.00")  # type: ignore[union-attr]
    assert c.total_taxes.amount == Decimal("34328.00")
    assert c.landed_cost.amount == Decimal("134328.00")


def test_el_iva_se_causa_sobre_las_demas_contribuciones() -> None:
    """El error más caro del cálculo aduanero.

    Si el IVA se calculara sobre el valor en aduana solo, saldría 16000.00 en
    vez de 18528.00: un número menor, plausible y equivocado. Nadie lo
    cuestiona hasta que llega una revisión.
    """
    c = compute_taxes(transaction_value=mxn("100000.00"), rates=TASAS)

    iva = c.item("IVA")
    assert iva is not None
    assert iva.amount.amount != Decimal("16000.00"), "el IVA no va sobre el valor en aduana solo"
    assert iva.amount.amount == Decimal("18528.00")
    # Seis decimales, no dos: los intermedios conservan la precisión de trabajo,
    # que es lo que permite repetir el cálculo y llegar al mismo número.
    assert iva.inputs["base_iva"] == "115800.000000"


def test_el_ieps_se_causa_sobre_valor_en_aduana_mas_igi() -> None:
    tasas = TaxRates(igi_rate=Decimal("0.10"), ieps_rate=Decimal("0.30"))

    c = compute_taxes(transaction_value=mxn("10000.00"), rates=tasas)

    # (10000 + 1000) * 0.30 = 3300.00
    assert c.item("IEPS").amount.amount == Decimal("3300.00")  # type: ignore[union-attr]


def test_la_cuota_fija_de_dta_sustituye_a_la_tasa() -> None:
    tasas = TaxRates(dta_rate=Decimal("0.008"), dta_fixed=Decimal("380.00"))

    c = compute_taxes(transaction_value=mxn("1000000.00"), rates=tasas)

    dta = c.item("DTA")
    assert dta is not None
    assert dta.amount.amount == Decimal("380.00")
    assert "cuota fija" in dta.formula


def test_la_cuota_compensatoria_solo_aparece_si_existe() -> None:
    """Una línea en cero ensucia el desglose sin aportar nada."""
    sin = compute_taxes(transaction_value=mxn("1000.00"), rates=TASAS)
    con = compute_taxes(
        transaction_value=mxn("1000.00"),
        rates=TaxRates(countervailing_rate=Decimal("0.25")),
    )

    assert sin.item("CUOTA_COMPENSATORIA") is None
    assert con.item("CUOTA_COMPENSATORIA").amount.amount == Decimal("250.00")  # type: ignore[union-attr]


# ── Trazabilidad: §22 exige que el cálculo se pueda repetir a mano ──────────


def test_cada_contribucion_expone_su_formula_y_sus_entradas() -> None:
    """Un número solo no se puede auditar. Con la fórmula, sí."""
    c = compute_taxes(transaction_value=mxn("100000.00"), rates=TASAS)

    for item in c.items:
        assert item.formula, f"{item.concept} sin fórmula"
        assert item.inputs, f"{item.concept} sin entradas"


def test_el_calculo_arrastra_las_fuentes_de_las_tasas() -> None:
    """Una tasa sin origen no es fundamento (§8.1)."""
    c = compute_taxes(transaction_value=mxn("100000.00"), rates=TASAS)

    assert "src-ligie-8471" in c.source_ids
    assert all("src-ligie-8471" in i.source_ids for i in c.items if i.rate is not None)


def test_todas_las_tasas_en_cero_levanta_un_supuesto() -> None:
    """Exento y "no se cargaron las tasas" producen el mismo cero, y no son
    lo mismo. El cálculo lo dice en vez de callarlo."""
    c = compute_taxes(transaction_value=mxn("100000.00"), rates=TaxRates())

    assert any("cero" in s for s in c.assumptions)


def test_es_simulacion_por_defecto() -> None:
    """§33: mientras no conste que los datos son reales, es una simulación."""
    c = compute_taxes(transaction_value=mxn("100.00"), rates=TASAS)

    assert c.is_simulation is True


def test_el_desglose_es_legible_para_que_un_llm_lo_narre() -> None:
    """El LLM explica lo ya calculado; nunca calcula (§22)."""
    c = compute_taxes(transaction_value=mxn("100000.00"), rates=TASAS)

    texto = c.explain()
    assert "IGI" in texto and "IVA" in texto
    assert "34,328.00 MXN" in texto
    assert "SIMULACIÓN" in texto


# ── Divergencia: la novena pregunta del §49 ─────────────────────────────────


def test_pagar_de_menos_es_omision() -> None:
    """Fracción declarada al 5% cuando correspondía el 15%."""
    declarado = compute_taxes(
        transaction_value=mxn("100000.00"),
        rates=TaxRates(igi_rate=Decimal("0.05"), iva_rate=Decimal("0.16")),
    )
    esperado = compute_taxes(
        transaction_value=mxn("100000.00"),
        rates=TaxRates(igi_rate=Decimal("0.15"), iva_rate=Decimal("0.16")),
    )

    impacto = compute_divergence(declared=declarado, expected=esperado)

    assert impacto.direction == "OMISION"
    assert impacto.is_underpayment
    # IGI: +10000 · IVA sobre esos 10000: +1600 → 11600
    assert impacto.difference.amount == Decimal("11600.00")
    assert impacto.by_concept["IGI"] == "10000.00"


def test_pagar_de_mas_es_sobrepago_y_es_una_oportunidad() -> None:
    """Un sobrepago puede ser recuperable: es otra conversación con el cliente."""
    declarado = compute_taxes(
        transaction_value=mxn("100000.00"), rates=TaxRates(igi_rate=Decimal("0.20"))
    )
    esperado = compute_taxes(
        transaction_value=mxn("100000.00"), rates=TaxRates(igi_rate=Decimal("0.10"))
    )

    impacto = compute_divergence(declared=declarado, expected=esperado)

    assert impacto.direction == "SOBREPAGO"
    assert impacto.is_overpayment
    assert impacto.difference.amount == Decimal("-10000.00")


def test_sin_diferencia_no_hay_hallazgo() -> None:
    c = compute_taxes(transaction_value=mxn("100000.00"), rates=TASAS)

    impacto = compute_divergence(declared=c, expected=c)

    assert impacto.direction == "SIN_DIFERENCIA"
    assert impacto.difference.is_zero
    assert not impacto.by_concept


def test_el_impacto_se_marca_como_simulado_para_el_dossier() -> None:
    """Un número sin esa marca se lee como real (§33)."""
    declarado = compute_taxes(
        transaction_value=mxn("100000.00"), rates=TaxRates(igi_rate=Decimal("0.05"))
    )
    esperado = compute_taxes(
        transaction_value=mxn("100000.00"), rates=TaxRates(igi_rate=Decimal("0.15"))
    )

    texto = compute_divergence(declared=declarado, expected=esperado).as_money_impact()

    assert "MXN" in texto
    assert "omitidos" in texto
    assert "(simulado)" in texto


def test_mezclar_real_con_sintetico_da_simulacion() -> None:
    """Un cálculo real combinado con uno sintético no produce un dato real."""
    real = compute_taxes(transaction_value=mxn("100.00"), rates=TASAS, is_simulation=False)
    sintetico = compute_taxes(transaction_value=mxn("100.00"), rates=TASAS)

    assert compute_divergence(declared=real, expected=sintetico).is_simulation is True


# ── Precisión ────────────────────────────────────────────────────────────────


def test_los_intermedios_no_se_redondean_a_dos_decimales() -> None:
    """Redondear en cada paso mete error en cada paso, no sólo en el resultado."""
    c = compute_taxes(
        transaction_value=mxn("333.33"),
        rates=TaxRates(igi_rate=Decimal("0.075"), iva_rate=Decimal("0.16")),
    )

    # IGI = 333.33 * 0.075 = 24.99975 → 25.00
    assert c.item("IGI").amount.amount == Decimal("25.00")  # type: ignore[union-attr]
    # La base del IVA usa el intermedio sin truncar: 333.33 + 24.99975 = 358.32975
    assert c.item("IVA").inputs["base_iva"] == "358.329750"  # type: ignore[union-attr]


def test_el_redondeo_es_media_hacia_arriba() -> None:
    """Convención fiscal. El de banquero haría 0.125 → 0.12, y a un auditor eso
    le parece un centavo perdido."""
    assert Money(amount=Decimal("0.125"), currency="MXN").quantize().amount == Decimal("0.13")
    assert Money(amount=Decimal("0.135"), currency="MXN").quantize().amount == Decimal("0.14")
