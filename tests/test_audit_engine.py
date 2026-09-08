"""Tests del Audit Engine.

Lo que más importa aquí no es que sume bien: es que NO invente montos donde no
los hay, y que no cuente el mismo dinero dos veces. Un informe con cifras
infladas se descubre en la primera revisión con el cliente, y con él se va la
confianza en todo lo demás.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.audit import ESCALA, audit, severity_for_amount
from core.shadow import DeclaredItem, DivergenceType, ExpectedItem, compare
from core.taxation import Money, TaxRates

pytestmark = pytest.mark.unit

VALOR = Money(amount=Decimal("100000.00"), currency="MXN")
TASAS_DECLARADAS = TaxRates(igi_rate=Decimal("0.05"), iva_rate=Decimal("0.16"))
TASAS_ESPERADAS = TaxRates(igi_rate=Decimal("0.15"), iva_rate=Decimal("0.16"))


def comparacion(**kw: object):  # type: ignore[no-untyped-def]
    dec: dict[str, object] = {
        "line_number": 1,
        "fraction_code": "84713099",
        "nico_code": "00",
        "country_of_origin": "CN",
        "customs_value": Decimal("100000.00"),
        "customs_value_currency": "MXN",
        "applied_nom_codes": ("NOM-019-SCFI",),
    }
    esp: dict[str, object] = {
        "line_number": 1,
        "fraction_code": "84713001",
        "nico_code": "00",
        "country_of_origin": "CN",
        "customs_value": Decimal("100000.00"),
        "customs_value_currency": "MXN",
        "required_nom_codes": ("NOM-019-SCFI",),
        # Explícito: se SABE que la operación no exige identificadores.
        # Sin esto la partida sería «no verificable» y ningún test podría
        # afirmar que un pedimento está limpio — que es justamente la regla.
        "required_identifiers": (),
        "is_resolved": True,
        "confidence": Decimal("0.92"),
    }
    dec.update(kw.get("declarado", {}))  # type: ignore[arg-type]
    esp.update(kw.get("esperado", {}))  # type: ignore[arg-type]
    return compare([DeclaredItem(**dec)], [ExpectedItem(**esp)])  # type: ignore[arg-type]


def auditar(**kw: object):  # type: ignore[no-untyped-def]
    base: dict[str, object] = {
        "transaction_value": VALOR,
        "declared_rates": TASAS_DECLARADAS,
        "expected_rates": TASAS_ESPERADAS,
    }
    comp = kw.pop("comparison", None) or comparacion()
    base.update(kw)
    return audit(comp, **base)  # type: ignore[arg-type]


# ── El caso completo ─────────────────────────────────────────────────────────


def test_una_fraccion_equivocada_produce_un_hallazgo_con_su_monto() -> None:
    """«La fracción está mal» → «son 11,600 pesos omitidos»."""
    r = auditar()

    h = next(f for f in r.findings if f.divergence.kind is DivergenceType.FRACTION_MISMATCH)
    assert h.impact_amount == Decimal("11600.00")
    assert h.impact_currency == "MXN"
    assert h.impact_direction == "OMISION"
    assert h.is_actionable


def test_el_informe_resume_la_exposicion_total() -> None:
    r = auditar()

    assert r.total_exposure == Decimal("11600.00")
    assert r.currency == "MXN"
    assert "omitidas" in r.summary()


def test_un_sobrepago_es_oportunidad_no_riesgo() -> None:
    """Otra conversación con el cliente: no «tienes un problema» sino
    «pagaste de más»."""
    r = auditar(
        declared_rates=TaxRates(igi_rate=Decimal("0.20")),
        expected_rates=TaxRates(igi_rate=Decimal("0.10")),
    )

    assert r.opportunities
    assert r.opportunities[0].is_opportunity
    assert r.total_recoverable is not None
    assert "recuperable" in r.summary()


# ── Lo que el motor debe NEGARSE a inventar ──────────────────────────────────


def test_sin_tasas_los_hallazgos_van_sin_impacto() -> None:
    """Es un resultado honesto, no un fallo.

    Sin tasas el hallazgo sigue siendo válido como riesgo de cumplimiento.
    Ponerle un monto aproximado para que la tabla se vea completa sería
    inventar (§36).
    """
    r = audit(comparacion())

    assert r.findings
    assert all(f.impact_amount is None for f in r.findings)
    assert not any(f.is_actionable for f in r.findings)
    assert any("sin impacto económico" in f.assumptions[0] for f in r.findings)


def test_una_nom_faltante_no_recibe_monto_inventado() -> None:
    """Detiene la mercancía pero no altera las contribuciones.

    Un número plausible es peor que un hueco declarado: el hueco se ve.
    """
    r = auditar(comparison=comparacion(declarado={"applied_nom_codes": ()}))

    nom = next(f for f in r.findings if f.divergence.kind is DivergenceType.MISSING_NOM)
    assert nom.impact_amount is None
    assert not nom.is_actionable
    assert "no cuantificado" in nom.explain()


def test_el_total_no_cuenta_el_mismo_dinero_dos_veces() -> None:
    """Dos divergencias pueden explicar UNA sola diferencia de contribuciones.

    Sumar el monto de cada hallazgo daría 23,200 cuando la diferencia real es
    11,600. Un informe inflado se descubre en la primera revisión con el
    cliente.
    """
    r = auditar(
        comparison=comparacion(
            declarado={"fraction_code": "84713099", "country_of_origin": "US"},
            esperado={"country_of_origin": "CN"},
        )
    )

    cuantificados = [f for f in r.findings if f.impact_amount is not None]
    assert len(cuantificados) == 2, "fracción y origen, ambas cuantificables"
    assert r.total_exposure == Decimal("11600.00"), "no 23,200"


# ── Severidad ────────────────────────────────────────────────────────────────


def test_el_monto_puede_subir_la_severidad() -> None:
    """Un origen equivocado de medio millón merece más atención que uno de mil.

    Se prueba con ORIGIN_MISMATCH y no con FRACTION_MISMATCH: la fracción ya es
    CRITICAL por su tipo, así que no puede subir y el test no demostraría nada.
    """
    r = auditar(
        comparison=comparacion(
            declarado={"fraction_code": "84713001", "country_of_origin": "US"},
            esperado={"country_of_origin": "CN"},
        ),
        transaction_value=Money(amount=Decimal("5000000.00"), currency="MXN"),
        declared_rates=TaxRates(igi_rate=Decimal("0.05")),
        expected_rates=TaxRates(igi_rate=Decimal("0.20")),
    )

    h = next(f for f in r.findings if f.divergence.kind is DivergenceType.ORIGIN_MISMATCH)
    assert h.divergence.severity == "HIGH", "la severidad del tipo"
    assert h.severity == "CRITICAL", "elevada por el monto"


def test_el_monto_nunca_baja_la_severidad() -> None:
    """Un NOM faltante detiene la mercancía valga lo que valga.

    Rebajarlo porque el monto es pequeño sería confundir «barato» con «leve».
    """
    r = auditar(comparison=comparacion(declarado={"applied_nom_codes": ()}))

    nom = next(f for f in r.findings if f.divergence.kind is DivergenceType.MISSING_NOM)
    assert nom.severity == "HIGH", "el tipo pone el suelo"


def test_una_severidad_elevada_explica_por_que() -> None:
    """Un ajuste sin explicación es una decisión que nadie puede revisar."""
    r = auditar(
        comparison=comparacion(
            declarado={"fraction_code": "84713001", "country_of_origin": "US"},
            esperado={"country_of_origin": "CN"},
        ),
        transaction_value=Money(amount=Decimal("5000000.00"), currency="MXN"),
        declared_rates=TaxRates(igi_rate=Decimal("0.05")),
        expected_rates=TaxRates(igi_rate=Decimal("0.20")),
    )

    h = next(f for f in r.findings if f.severity_reason)
    assert "Severidad elevada" in h.severity_reason  # type: ignore[operator]
    assert h.severity_reason in h.to_finding_fields()["rationale"]  # type: ignore[operator]


@pytest.mark.parametrize(
    ("monto", "esperado"),
    [
        (Decimal("600000"), "CRITICAL"),
        (Decimal("150000"), "HIGH"),
        (Decimal("50000"), "MEDIUM"),
        (Decimal("5000"), "LOW"),
        (Decimal("500"), "INFO"),
    ],
)
def test_los_umbrales_de_monto(monto: Decimal, esperado: str) -> None:
    assert severity_for_amount(monto) == esperado


def test_un_sobrepago_grande_tambien_escala() -> None:
    """El signo no cambia la magnitud: 500 mil de más importan igual."""
    assert severity_for_amount(Decimal("-600000")) == "CRITICAL"


def test_la_escala_esta_ordenada() -> None:
    assert ESCALA == ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")


# ── Lo no verificable ────────────────────────────────────────────────────────


def test_lo_no_verificable_se_hereda_del_espejo() -> None:
    """«No encontré nada» y «no pude revisarlo» siguen siendo distintos (§36)."""
    r = auditar(comparison=comparacion(esperado={"is_resolved": False}))

    assert not r.is_complete
    assert r.unverifiable
    assert "no se pudieron comprobar" in r.summary()


def test_un_pedimento_limpio_se_puede_afirmar_limpio() -> None:
    r = auditar(comparison=comparacion(declarado={"fraction_code": "84713001"}))

    assert not r.findings
    assert r.is_complete
    assert "Sin hallazgos" in r.summary()


# ── Frontera con la persistencia ─────────────────────────────────────────────


def test_el_mapeo_a_risk_findings_lleva_el_impacto() -> None:
    """§29: dict plano; el `impact_amount` de la tabla es lo que llena esto."""
    r = auditar()

    campos = r.findings[0].to_finding_fields()
    assert campos["finding_type"] == "FRACTION_MISMATCH"
    assert campos["impact_amount"] == Decimal("11600.00")
    assert campos["impact_amount_currency"] == "MXN"
    assert campos["is_simulation"] is True
    assert campos["rationale"]


def test_es_simulacion_por_defecto() -> None:
    """§33: mientras no conste que los datos son reales."""
    assert auditar().is_simulation is True
    assert all(f.is_simulation for f in auditar().findings)
