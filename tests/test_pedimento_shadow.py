"""Tests del Pedimento Espejo.

El test más importante de este módulo no es que detecte divergencias: es que se
ABSTENGA cuando no puede sostener su expectativa. Acusar a un agente aduanal de
un error que acarrea multa, sin fundamento, destruye la confianza en el sistema
más rápido de lo que cualquier acierto la construye.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.shadow import DeclaredItem, DivergenceType, ExpectedItem, compare

pytestmark = pytest.mark.unit


def declarado(**kw: object) -> DeclaredItem:
    base: dict[str, object] = {
        "line_number": 1,
        "description": "Computadora portátil",
        "fraction_code": "84713001",
        "nico_code": "00",
        "country_of_origin": "CN",
        "customs_value": Decimal("100000.00"),
        "customs_value_currency": "MXN",
        "applied_nom_codes": ("NOM-019-SCFI",),
        "sku": "LAP-14-8GB",
    }
    base.update(kw)
    return DeclaredItem(**base)  # type: ignore[arg-type]


def esperado(**kw: object) -> ExpectedItem:
    base: dict[str, object] = {
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
        "confidence": Decimal("0.92"),
        "is_resolved": True,
        "sku": "LAP-14-8GB",
    }
    base.update(kw)
    return ExpectedItem(**base)  # type: ignore[arg-type]


# ── Cuando todo coincide ─────────────────────────────────────────────────────


def test_un_pedimento_correcto_no_produce_hallazgos() -> None:
    r = compare([declarado()], [esperado()])

    assert not r.has_findings
    assert r.is_complete
    assert "Sin divergencias" in r.summary()


# ── Lo que el espejo debe DETECTAR ───────────────────────────────────────────


def test_fraccion_distinta_es_critica() -> None:
    """Cambia el arancel: multa, crédito fiscal y posible embargo."""
    r = compare([declarado(fraction_code="84713099")], [esperado()])

    d = r.divergences[0]
    assert d.kind is DivergenceType.FRACTION_MISMATCH
    assert d.severity == "CRITICAL"
    assert d.declared_value == "84713099"
    assert d.expected_value == "84713001"
    assert r.worst_severity == "CRITICAL"


def test_una_partida_sin_fraccion_tambien_es_hallazgo() -> None:
    r = compare([declarado(fraction_code=None)], [esperado()])

    assert r.divergences[0].kind is DivergenceType.FRACTION_MISMATCH
    assert r.divergences[0].declared_value is None


def test_nom_faltante_detiene_la_mercancia() -> None:
    r = compare([declarado(applied_nom_codes=())], [esperado()])

    d = next(x for x in r.divergences if x.kind is DivergenceType.MISSING_NOM)
    assert d.severity == "HIGH"
    assert d.expected_value == "NOM-019-SCFI"


def test_origen_distinto_puede_cambiar_la_preferencia() -> None:
    r = compare([declarado(country_of_origin="US")], [esperado(country_of_origin="CN")])

    d = next(x for x in r.divergences if x.kind is DivergenceType.ORIGIN_MISMATCH)
    assert d.severity == "HIGH"
    assert "preferencia arancelaria" in d.reasoning


def test_identificador_faltante_del_anexo_22() -> None:
    r = compare([declarado()], [esperado(required_identifiers=("TL",))])

    d = next(x for x in r.divergences if x.kind is DivergenceType.IDENTIFIER_MISMATCH)
    assert d.expected_value == "TL"


def test_valor_subvaluado_es_critico() -> None:
    """Subvaluar es de las infracciones más perseguidas."""
    r = compare([declarado(customs_value=Decimal("60000.00"))], [esperado()])

    d = next(x for x in r.divergences if x.kind is DivergenceType.VALUE_MISMATCH)
    assert d.severity == "CRITICAL"
    assert "40.0%" in d.reasoning


def test_una_diferencia_minima_de_valor_no_es_hallazgo() -> None:
    """Por debajo del 1% suele ser redondeo o tipo de cambio de otro día.

    Acusar por un peso arruinaría la señal: si el sistema reporta ruido, se
    deja de mirar lo que reporta.
    """
    r = compare([declarado(customs_value=Decimal("100050.00"))], [esperado()])

    assert not any(x.kind is DivergenceType.VALUE_MISMATCH for x in r.divergences)


def test_valores_en_divisas_distintas_no_se_restan() -> None:
    """Restar 100000 MXN de 100000 USD daría cero: una coincidencia falsa."""
    r = compare([declarado(customs_value_currency="USD")], [esperado(customs_value_currency="MXN")])

    d = next(x for x in r.divergences if x.kind is DivergenceType.VALUE_MISMATCH)
    assert d.field == "customs_value_currency"


def test_un_sku_clasificado_distinto_antes_es_hallazgo() -> None:
    """Sale del historial, no de la norma.

    No dice cuál es la correcta: dice que una de las dos operaciones tiene un
    error, y eso ya merece que alguien lo mire.
    """
    r = compare([declarado()], [esperado()], sku_history={"LAP-14-8GB": "84713099"})

    d = next(x for x in r.divergences if x.kind is DivergenceType.INCONSISTENT_SKU_CLASSIFICATION)
    assert "una de las dos operaciones tiene un error" in d.reasoning


# ── Lo que el espejo debe ABSTENERSE de afirmar ──────────────────────────────


def test_sin_clasificacion_defendible_no_se_acusa() -> None:
    """El test que define este módulo.

    Si el sistema no pudo sostener una clasificación, decir que la declarada
    está mal es acusar sin fundamento. Se declara no verificable.
    """
    r = compare([declarado(fraction_code="99999999")], [esperado(is_resolved=False)])

    assert not any(x.kind is DivergenceType.FRACTION_MISMATCH for x in r.divergences)
    assert r.unverifiable
    assert "no llegó a ser defendible" in r.unverifiable[0]
    assert not r.is_complete


def test_sin_clasificacion_aun_se_comprueba_lo_comprobable() -> None:
    """No poder clasificar no ciega al espejo del todo.

    El origen y las NOM no dependen de la fracción: siguen siendo verificables
    aunque la clasificación no se sostenga.
    """
    r = compare(
        [declarado(country_of_origin="US", applied_nom_codes=())],
        [esperado(is_resolved=False, country_of_origin="CN")],
    )

    tipos = {x.kind for x in r.divergences}
    assert DivergenceType.ORIGIN_MISMATCH in tipos
    assert DivergenceType.MISSING_NOM in tipos
    assert DivergenceType.FRACTION_MISMATCH not in tipos


def test_una_partida_sin_expectativa_no_se_juzga() -> None:
    """Sin espejo no hay comparación, y eso se dice."""
    r = compare([declarado(line_number=7)], [esperado(line_number=1)])

    assert not r.has_findings
    assert not r.is_complete
    assert "línea 7" in r.unverifiable[0]


def test_no_verificable_no_es_lo_mismo_que_limpio() -> None:
    """§36: confundirlos haría que un pedimento sin revisar pareciera correcto."""
    r = compare([declarado(line_number=7)], [esperado(line_number=1)])

    assert not r.has_findings
    assert "no se pudieron comprobar" in r.summary()


def test_el_nico_solo_se_compara_si_la_fraccion_coincide() -> None:
    """Comparar el NICO de dos fracciones distintas no dice nada útil, y
    duplicaría el hallazgo de la fracción."""
    r = compare(
        [declarado(fraction_code="84713099", nico_code="01")],
        [esperado(fraction_code="84713001", nico_code="00")],
    )

    assert not any(x.kind is DivergenceType.NICO_MISMATCH for x in r.divergences)
    assert any(x.kind is DivergenceType.FRACTION_MISMATCH for x in r.divergences)


# ── Frontera con la persistencia ─────────────────────────────────────────────


def test_el_mapeo_a_risk_findings_no_importa_la_capa_de_datos() -> None:
    """§29: dict plano; quien escribe la fila ensambla."""
    r = compare([declarado(fraction_code="84713099")], [esperado()])

    campos = r.divergences[0].to_finding_fields()
    assert campos["finding_type"] == "FRACTION_MISMATCH"
    assert campos["severity"] == "CRITICAL"
    assert campos["declared_value"] == "84713099"
    assert campos["requires_human_review"] is True


def test_la_confianza_de_la_expectativa_viaja_al_hallazgo() -> None:
    """Una divergencia contra una expectativa insegura no es una acusación
    firme, y el número tiene que dejarlo ver."""
    r = compare([declarado(fraction_code="84713099")], [esperado(confidence=Decimal("0.4200"))])

    assert r.divergences[0].confidence == Decimal("0.4200")


# ── No saber ≠ que no aplique ────────────────────────────────────────────────


def test_no_saber_que_nom_exige_la_fraccion_no_es_lo_mismo_que_no_exigir_ninguna() -> None:
    """`None` manda la partida a `unverifiable`; no la da por limpia.

    Es el bug que el hallazgo de Persona 2 volvió urgente: la correlación
    fracción → NOM no está en el Anexo 22 y no hay fuente cargada. Con el
    valor por omisión anterior —tupla vacía— el motor recorría cero NOM
    esperadas, no encontraba ninguna faltante, y el pedimento salía limpio sin
    que nadie hubiera comprobado nada.
    """
    r = compare(
        [declarado(applied_nom_codes=())],
        [esperado(required_nom_codes=None, required_identifiers=())],
    )

    assert not [x for x in r.divergences if x.kind is DivergenceType.MISSING_NOM]
    assert not r.is_complete
    assert any("NOM" in u for u in r.unverifiable)
    assert "no se pudieron comprobar" in r.summary()


def test_saber_que_no_exige_ninguna_nom_si_permite_afirmar_limpio() -> None:
    """La tupla vacía es una afirmación: «comprobé, no exige ninguna»."""
    r = compare(
        [declarado(applied_nom_codes=())],
        [esperado(required_nom_codes=(), required_identifiers=())],
    )

    assert r.is_complete
    assert "Sin divergencias" in r.summary()


def test_los_identificadores_desconocidos_se_reportan_aparte() -> None:
    """El Apéndice 8 está pendiente; la laguna se nombra, no se disimula."""
    r = compare([declarado()], [esperado(required_identifiers=None)])

    assert not r.is_complete
    assert any("Apéndice 8" in u for u in r.unverifiable)


def test_una_laguna_no_impide_detectar_lo_que_si_es_comprobable() -> None:
    """No saber de NOM no ciega el resto: la fracción se sigue comparando."""
    r = compare(
        [declarado(fraction_code="85285900")],
        [esperado(required_nom_codes=None, required_identifiers=None)],
    )

    assert [x for x in r.divergences if x.kind is DivergenceType.FRACTION_MISMATCH]
    assert not r.is_complete
