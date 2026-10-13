"""El cálculo del §22 viaja con el hallazgo, no sólo la cifra.

Antes del 13-oct, `core/taxation` producía fórmula, entradas, versión y
supuestos, y al guardar el hallazgo sólo sobrevivían el importe y la divisa.
Quien abría «4 822.95 MXN» no tenía cómo rehacerlo.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.audit import audit
from core.shadow import DeclaredItem, DivergenceType, ExpectedItem, compare
from core.taxation import Money, TaxRates

pytestmark = pytest.mark.unit

CAMPOS_22 = {
    "formula",
    "inputs",
    "result",
    "currency",
    "calculation_version",
    "assumptions",
    "source_ids",
    "is_simulation",
}
VALOR = Money(amount=Decimal("100000.00"), currency="MXN")


def _fraccion_equivocada():  # type: ignore[no-untyped-def]
    comparacion = compare(
        [DeclaredItem(line_number=1, fraction_code="85285900")],
        [
            ExpectedItem(
                line_number=1,
                fraction_code="84713001",
                is_resolved=True,
                confidence=Decimal("1"),
            )
        ],
    )
    return audit(
        comparacion,
        transaction_value=VALOR,
        declared_rates=TaxRates(igi_rate=Decimal("0.15"), source_ids=("tarifa-8528",)),
        expected_rates=TaxRates(igi_rate=Decimal("0.00"), source_ids=("tarifa-8471",)),
        is_simulation=True,
    )


def test_el_impacto_de_una_fraccion_lleva_los_ocho_campos() -> None:
    [f] = [x for x in _fraccion_equivocada().findings if x.impact_amount is not None]
    calculo = f.calculation
    assert calculo is not None
    assert set(calculo.model_dump()) == CAMPOS_22
    assert Decimal(calculo.result) == f.impact_amount
    assert calculo.currency == "MXN"
    assert calculo.is_simulation is True


def test_las_entradas_bastan_para_rehacerlo_a_mano() -> None:
    [f] = [x for x in _fraccion_equivocada().findings if x.impact_amount is not None]
    entradas = f.calculation.inputs  # type: ignore[union-attr]
    assert Decimal(entradas["total_esperado"]) - Decimal(entradas["total_declarado"]) == (
        f.impact_amount
    )
    assert "valor_aduana(100000.00) × 0.15" in entradas["declarado.IGI"]


def test_las_fuentes_de_las_dos_tarifas_viajan() -> None:
    [f] = [x for x in _fraccion_equivocada().findings if x.impact_amount is not None]
    assert {"tarifa-8528", "tarifa-8471"} <= set(f.calculation.source_ids)  # type: ignore[union-attr]


def test_el_error_de_una_contribucion_lleva_como_salio_el_esperado() -> None:
    derivacion = "valor_aduana(100000.00) × tasa_IGI 84713001 (0.15) = 15000.00"
    comparacion = compare(
        [DeclaredItem(line_number=1, fraction_code="84713001", igi_amount=Decimal("5000.00"))],
        [
            ExpectedItem(
                line_number=1,
                igi_amount=Decimal("15000.00"),
                derivations={"igi_amount": derivacion},
            )
        ],
    )
    [d] = [x for x in comparacion.divergences if x.kind is DivergenceType.IGI_RATE_MISMATCH]
    assert d.derivation == derivacion

    [f] = audit(comparacion, transaction_value=VALOR, is_simulation=False).findings
    calculo = f.calculation
    assert calculo is not None
    assert calculo.result == "10000.00"
    assert calculo.inputs["igi_amount_esperado.derivacion"] == derivacion
    assert calculo.is_simulation is False


def test_sin_monto_no_hay_calculo() -> None:
    comparacion = compare(
        [DeclaredItem(line_number=1, applied_nom_codes=())],
        [ExpectedItem(line_number=1, required_nom_codes=("NOM-001",))],
    )
    [f] = audit(comparacion).findings
    assert f.impact_amount is None
    assert f.calculation is None
    assert f.to_finding_fields()["impact_calculation"] is None


def test_el_calculo_se_serializa_para_la_fila() -> None:
    [f] = [x for x in _fraccion_equivocada().findings if x.impact_amount is not None]
    fila = f.to_finding_fields()["impact_calculation"]
    assert isinstance(fila, dict)
    assert set(fila) == CAMPOS_22


# ── Las oportunidades también (13-oct) ───────────────────────────────────────


def test_un_sobrepago_lleva_el_calculo_del_hallazgo_en_positivo() -> None:
    from core.opportunity import find_opportunities

    informe = audit(
        compare(
            [DeclaredItem(line_number=1, fraction_code="85285900")],
            [
                ExpectedItem(
                    line_number=1,
                    fraction_code="84713001",
                    is_resolved=True,
                    confidence=Decimal("1"),
                )
            ],
        ),
        transaction_value=VALOR,
        declared_rates=TaxRates(igi_rate=Decimal("0.15")),
        expected_rates=TaxRates(igi_rate=Decimal("0.00")),
    )
    [o] = find_opportunities(audit=informe).opportunities
    assert o.calculation is not None
    assert Decimal(o.calculation.result) == o.estimated_saving > 0
    assert o.calculation.formula.startswith("-(")


def test_una_tasa_preferencial_lleva_los_dos_calculos() -> None:
    from core.opportunity import OpportunityKind, from_preferential_rate

    o = from_preferential_rate(
        kind=OpportunityKind.PROSEC,
        transaction_value=VALOR,
        applied_rates=TaxRates(igi_rate=Decimal("0.15"), source_ids=("ligie",)),
        preferential_rates=TaxRates(igi_rate=Decimal("0.05"), source_ids=("prosec",)),
        rationale="",
    )
    calculo = o.calculation
    assert calculo is not None
    assert Decimal(calculo.result) == o.estimated_saving == Decimal("10000.00")
    assert "con_la_tasa_aplicada.IGI" in calculo.inputs
    assert "con_la_tasa_preferencial.IGI" in calculo.inputs
    assert {"ligie", "prosec"} <= set(calculo.source_ids)


def test_una_oportunidad_sin_monto_no_lleva_calculo() -> None:
    from core.opportunity import OpportunityKind, from_preferential_rate

    o = from_preferential_rate(
        kind=OpportunityKind.PROSEC,
        transaction_value=VALOR,
        applied_rates=TaxRates(igi_rate=Decimal("0.05")),
        preferential_rates=TaxRates(igi_rate=Decimal("0.10")),
        rationale="",
    )
    assert o.estimated_saving is None
    assert o.calculation is None
