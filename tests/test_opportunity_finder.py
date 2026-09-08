"""Tests del Opportunity Finder.

Lo que más se prueba aquí es la disciplina, no el cálculo: que nada salga
pareciendo un ahorro confirmado. Un informe que promete dinero que el cliente
no puede cobrar destruye la relación en la primera reunión, y con ella la
credibilidad de todo lo demás que diga el sistema.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.audit import audit
from core.opportunity import (
    CONDITIONS,
    OpportunityKind,
    build,
    find_opportunities,
    from_preferential_rate,
)
from core.shadow import DeclaredItem, ExpectedItem, compare
from core.taxation import Money, TaxRates

pytestmark = pytest.mark.unit

VALOR = Money(amount=Decimal("100000.00"), currency="MXN")


def comparacion_con_sobrepago():  # type: ignore[no-untyped-def]
    """Un pedimento con la fracción equivocada, declarada con tasa MAYOR."""
    return compare(
        [
            DeclaredItem(
                line_number=1,
                fraction_code="84713099",
                country_of_origin="CN",
                customs_value=Decimal("100000.00"),
                customs_value_currency="MXN",
            )
        ],
        [
            ExpectedItem(
                line_number=1,
                fraction_code="84713001",
                country_of_origin="CN",
                customs_value=Decimal("100000.00"),
                customs_value_currency="MXN",
                is_resolved=True,
                confidence=Decimal("0.92"),
            )
        ],
    )


def informe_de_auditoria(declarada: str = "0.20", esperada: str = "0.10"):  # type: ignore[no-untyped-def]
    return audit(
        comparacion_con_sobrepago(),
        transaction_value=VALOR,
        declared_rates=TaxRates(igi_rate=Decimal(declarada), iva_rate=Decimal("0.16")),
        expected_rates=TaxRates(igi_rate=Decimal(esperada), iva_rate=Decimal("0.16")),
    )


# ── La disciplina del §23 ────────────────────────────────────────────────────


def test_toda_oportunidad_nace_potencial() -> None:
    """§23: POTENTIAL nunca se presenta como ahorro garantizado.

    Ni siquiera un sobrepago comprobado nace VALIDATED: que se pagó de más es
    un hecho, que se pueda recuperar depende de plazos que el motor no conoce.
    """
    r = find_opportunities(audit=informe_de_auditoria())

    assert r.opportunities
    assert all(o.status == "POTENTIAL" for o in r.opportunities)


def test_no_se_puede_construir_una_oportunidad_sin_condiciones() -> None:
    """Es lo que impide que salga del sistema pareciendo un hecho."""
    for kind in OpportunityKind:
        o = build(kind, rationale="prueba")
        assert o.conditions, f"{kind.value} sin condiciones"
        assert o.conditions == CONDITIONS[kind]


def test_las_condiciones_viajan_al_razonamiento_persistido() -> None:
    """Van juntas a propósito: quien lea la FILA tiene que ver que es una
    hipótesis, no sólo quien mire la pantalla.

    Separarlas permitiría que un informe cite el monto sin las condiciones.
    """
    campos = build(
        OpportunityKind.PROSEC, rationale="La fracción está en el sector electrónico."
    ).to_finding_fields()

    assert "Por verificar" in campos["rationale"]
    assert "inscrito en el programa PROSEC" in campos["rationale"]
    assert campos["status"] == "POTENTIAL"


def test_prosec_exige_comprobar_la_inscripcion() -> None:
    """Que una fracción esté en un sector no dice si el importador puede usarlo."""
    o = build(OpportunityKind.PROSEC, rationale="x")

    assert any("inscrito" in c for c in o.conditions)
    assert any("vigente en la fecha de la operación" in c for c in o.conditions)


def test_una_preferencia_exige_certificado_de_origen() -> None:
    o = build(OpportunityKind.TRADE_PREFERENCE, rationale="x")

    assert any("certificado de origen" in c for c in o.conditions)
    assert any("regla de origen" in c for c in o.conditions)


# ── El sobrepago, único tipo que se cuantifica solo ─────────────────────────


def test_un_sobrepago_del_audit_se_convierte_en_oportunidad() -> None:
    r = find_opportunities(audit=informe_de_auditoria())

    o = r.by_kind(OpportunityKind.OVERPAYMENT)
    assert o
    assert o[0].is_quantified
    assert o[0].currency == "MXN"
    assert "de más" in o[0].rationale


def test_una_omision_no_es_oportunidad() -> None:
    """Pagar de MENOS es riesgo, no ahorro. Confundirlos sería grave."""
    r = find_opportunities(audit=informe_de_auditoria(declarada="0.05", esperada="0.15"))

    assert not r.by_kind(OpportunityKind.OVERPAYMENT)


# ── Las tasas preferenciales vienen de fuera ────────────────────────────────


def test_el_ahorro_de_una_tasa_preferencial_se_calcula_con_las_dos() -> None:
    """IGI 15% → 5% sobre 100,000: 10,000 de IGI más su IVA."""
    o = from_preferential_rate(
        kind=OpportunityKind.PROSEC,
        transaction_value=VALOR,
        applied_rates=TaxRates(igi_rate=Decimal("0.15"), iva_rate=Decimal("0.16")),
        preferential_rates=TaxRates(igi_rate=Decimal("0.05"), iva_rate=Decimal("0.16")),
        rationale="La fracción pertenece al sector electrónico de PROSEC.",
    )

    assert o.estimated_saving == Decimal("11600.00")
    assert o.status == "POTENTIAL"
    assert o.conditions


def test_una_preferencial_que_no_ahorra_no_lleva_monto() -> None:
    """«Podrías pagar más» no es una oportunidad.

    Un número con signo raro en un informe es lo que hace que dejen de leerlo.
    """
    o = from_preferential_rate(
        kind=OpportunityKind.PROSEC,
        transaction_value=VALOR,
        applied_rates=TaxRates(igi_rate=Decimal("0.05")),
        preferential_rates=TaxRates(igi_rate=Decimal("0.15")),
        rationale="x",
    )

    assert o.estimated_saving is None
    assert not o.is_actionable


# ── Lo que el motor NO puede evaluar, lo declara ────────────────────────────


def test_declara_que_no_evaluo_prosec_ni_preferencias() -> None:
    """«No encontré oportunidades» y «no pude buscarlas» son cosas distintas.

    Sin esta nota, un informe vacío parecería decir que no hay nada que
    aprovechar — cuando en realidad ni se miró.
    """
    r = find_opportunities(audit=informe_de_auditoria())

    assert any("no se evaluaron" in n for n in r.notes)
    assert any("NO significa que no existan" in n for n in r.notes)


def test_sin_auditoria_lo_dice() -> None:
    r = find_opportunities()

    assert not r.opportunities
    assert any("Sin informe de auditoría" in n for n in r.notes)
    assert "Sin oportunidades" in r.summary()


# ── El total es un techo, no un pronóstico ──────────────────────────────────


def test_el_total_se_presenta_como_techo_no_como_ahorro() -> None:
    """Un total suena más firme que cada parte, así que el resumen lo desarma.

    Cada sumando es una hipótesis con condiciones propias.
    """
    prosec = from_preferential_rate(
        kind=OpportunityKind.PROSEC,
        transaction_value=VALOR,
        applied_rates=TaxRates(igi_rate=Decimal("0.15"), iva_rate=Decimal("0.16")),
        preferential_rates=TaxRates(igi_rate=Decimal("0.05"), iva_rate=Decimal("0.16")),
        rationale="Sector electrónico.",
    )
    r = find_opportunities(audit=informe_de_auditoria(), extra=[prosec])

    texto = r.summary()
    assert "Techo si todas se confirman" in texto
    assert "Ninguna está confirmada todavía" in texto
    assert r.total_potential is not None


def test_lo_no_cuantificado_se_cuenta_aparte() -> None:
    """«Podrías ahorrar algo» no mueve a nadie a revisar un pedimento."""
    sin_monto = build(OpportunityKind.REGLA_8A, rationale="Podría aplicar la Regla 8ª.")
    r = find_opportunities(audit=informe_de_auditoria(), extra=[sin_monto])

    assert not sin_monto.is_actionable
    assert len(r.actionable) < len(r.opportunities)
    assert "sin cuantificar" in r.summary()


def test_es_simulacion_por_defecto() -> None:
    """§33: mientras no conste que los datos son reales."""
    r = find_opportunities(audit=informe_de_auditoria())

    assert r.is_simulation
    assert "(simulado)" in r.summary()


def test_el_relato_lista_las_condiciones() -> None:
    """Quien lea una oportunidad tiene que ver qué falta comprobar."""
    texto = build(
        OpportunityKind.PROSEC,
        rationale="Sector electrónico.",
        estimated_saving=Decimal("11600.00"),
        currency="MXN",
    ).explain()

    assert "POTENTIAL" in texto
    assert "11,600.00 MXN" in texto
    assert "inscrito en el programa PROSEC" in texto
