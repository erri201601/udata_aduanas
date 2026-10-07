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
        "unit": "6",
        "igi_amount": Decimal("15000.00"),
        "vat_amount": Decimal("18528.00"),
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
        # Explícito: se comprobó y cuadra. Sin esto la partida sería «no
        # verificable» y ningún test podría afirmar que un pedimento está limpio.
        "igi_amount": Decimal("15000.00"),
        "vat_amount": Decimal("18528.00"),
        "declared_unit_is_known": True,
        # Explícito: se consultó la ficha y no le falta nada. `None` diría que
        # no se consultó, y la partida no podría declararse limpia.
        "missing_technical_fields": (),
        "sku": "LAP-14-8GB",
        # Explícito, sólo para el fixture: en producción el router nunca
        # construye `False` (ver docstring del campo) -- pero el TIPO sí lo
        # admite, y sin esto ningún test podría afirmar "pedimento limpio".
        "compensatory_duty_applies": False,
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


# ── Tipo de cambio ────────────────────────────────────────────────────────


def test_tipo_de_cambio_distinto_es_critico() -> None:
    """Cambia el valor en aduana convertido, igual que una subvaluación."""
    r = compare(
        [declarado(exchange_rate=Decimal("17.0000"))],
        [esperado(exchange_rate=Decimal("20.0000"))],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.EXCHANGE_RATE_MISMATCH)
    assert d.severity == "CRITICAL"
    assert d.declared_value == "17.0000"
    assert d.expected_value == "20.0000"


def test_una_diferencia_minima_de_tipo_de_cambio_no_es_hallazgo() -> None:
    """Por debajo del 1% es ruido de redondeo, no un tipo de cambio mal."""
    r = compare(
        [declarado(exchange_rate=Decimal("20.05"))],
        [esperado(exchange_rate=Decimal("20.00"))],
    )

    assert not any(x.kind is DivergenceType.EXCHANGE_RATE_MISMATCH for x in r.divergences)


def test_sin_fix_cargado_el_tipo_de_cambio_no_se_acusa() -> None:
    """`expected.exchange_rate is None` es «no se pudo comprobar», no «coincide» —
    no se emite un hallazgo sobre una base que no se tiene."""
    r = compare(
        [declarado(exchange_rate=Decimal("20.00"))],
        [esperado(exchange_rate=None)],
    )

    assert not any(x.kind is DivergenceType.EXCHANGE_RATE_MISMATCH for x in r.divergences)


# ── Cuota compensatoria (ADR 0009) ────────────────────────────────────────


def test_cuota_compensatoria_no_declarada_con_monto_conocido() -> None:
    r = compare(
        [declarado(cc_amount=None)],
        [esperado(compensatory_duty_applies=True, compensatory_duty_amount=Decimal("500.00"))],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.COMPENSATORY_DUTY_MISMATCH)
    assert d.severity == "CRITICAL"
    assert d.declared_value is None
    assert d.expected_value == "500.00"


def test_cuota_compensatoria_no_declarada_sin_monto_calculable_tambien_es_hallazgo() -> None:
    """La unidad declarada no es la de la cuota (p. ej. metro lineal contra
    "por kilogramo") -- no se inventa un factor de conversión, pero el
    hallazgo se emite igual: SÍ se sabe que la cuota aplica."""
    r = compare(
        [declarado(cc_amount=None)],
        [esperado(compensatory_duty_applies=True, compensatory_duty_amount=None)],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.COMPENSATORY_DUTY_MISMATCH)
    assert d.expected_value is None
    assert "no se pudo calcular" in d.reasoning


def test_cuota_compensatoria_declarada_pero_no_cuadra() -> None:
    r = compare(
        [declarado(cc_amount=Decimal("100.00"))],
        [esperado(compensatory_duty_applies=True, compensatory_duty_amount=Decimal("500.00"))],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.COMPENSATORY_DUTY_MISMATCH)
    assert d.declared_value == "100.00"
    assert d.expected_value == "500.00"


def test_cuota_compensatoria_declarada_y_cuadra_no_es_hallazgo() -> None:
    r = compare(
        [declarado(cc_amount=Decimal("500.00"))],
        [esperado(compensatory_duty_applies=True, compensatory_duty_amount=Decimal("500.00"))],
    )

    assert not any(x.kind is DivergenceType.COMPENSATORY_DUTY_MISMATCH for x in r.divergences)


def test_sin_cuota_conocida_no_se_acusa() -> None:
    """`compensatory_duty_applies is None` es «no se sabe», no «no aplica» —
    no se emite un hallazgo sobre una combinación sin verificar."""
    r = compare(
        [declarado(cc_amount=None)],
        [esperado(compensatory_duty_applies=None)],
    )

    assert not any(x.kind is DivergenceType.COMPENSATORY_DUTY_MISMATCH for x in r.divergences)


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


# ── El país contra el proveedor (Persona 1, 21-sep) ─────────────────────────


def test_el_origen_del_proveedor_pide_revision_no_acusa() -> None:
    """EL TEST QUE IMPORTA.

    Un pedimento con orígenes mixtos es legítimo. Si esto saliera como error
    duro, en cuanto lleguen pedimentos reales nos llenamos de falsos
    positivos.
    """
    from core.shadow.types import ORIGEN_DEL_PROVEEDOR

    r = compare(
        [declarado(country_of_origin="BR")],
        [esperado(country_of_origin="CN", origin_source=ORIGEN_DEL_PROVEEDOR)],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.ORIGIN_MISMATCH)
    assert d.severity == "MEDIUM", "no es una acusación"
    assert d.requires_human_review is True
    assert "orígenes mixtos es legítimo" in d.reasoning
    assert "certificado de origen" in d.reasoning
    assert d.declared_value == "BR"
    assert d.expected_value == "CN"


def test_una_fuente_firme_sigue_siendo_hallazgo_duro() -> None:
    """Lo que cambia es de dónde sale la expectativa, no el tipo de divergencia."""
    r = compare([declarado(country_of_origin="BR")], [esperado(country_of_origin="CN")])

    d = next(x for x in r.divergences if x.kind is DivergenceType.ORIGIN_MISMATCH)
    assert d.severity == "HIGH"
    assert "preferencia arancelaria" in d.reasoning


def test_el_mismo_pais_que_el_proveedor_no_produce_nada() -> None:
    from core.shadow.types import ORIGEN_DEL_PROVEEDOR

    r = compare(
        [declarado(country_of_origin="CN")],
        [esperado(country_of_origin="CN", origin_source=ORIGEN_DEL_PROVEEDOR)],
    )

    assert not [x for x in r.divergences if x.kind is DivergenceType.ORIGIN_MISMATCH]


def test_sin_pais_del_proveedor_la_partida_lo_declara() -> None:
    """No se da por limpia: se dice que no se pudo contrastar."""
    r = compare([declarado(country_of_origin="BR")], [esperado(country_of_origin=None)])

    assert not [x for x in r.divergences if x.kind is DivergenceType.ORIGIN_MISMATCH]
    assert any("país del proveedor" in motivo for motivo in r.unverifiable)


# ── NICO contra el catálogo y valor contra la propia partida (21-sep) ───────


def test_un_nico_que_no_existe_en_la_fraccion_es_hallazgo() -> None:
    """Lo único que el catálogo puede afirmar solo.

    No hace falta saber cuál es el NICO correcto para saber que éste no lo es.
    """
    r = compare(
        [declarado(fraction_code="73241001", nico_code="99")],
        [esperado(fraction_code="73241001", nico_code=None, valid_nico_codes=("00",))],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.NICO_MISMATCH)
    assert d.declared_value == "99"
    assert d.expected_value is None, "no se inventa cuál era el correcto"
    assert "no existe en la fracción 73241001" in d.reasoning
    assert "Los vigentes son: 00" in d.reasoning


def test_un_nico_que_sí_existe_no_se_acusa_y_se_declara_el_hueco() -> None:
    """Que exista NO significa que sea el correcto: eso exige clasificar hasta el NICO.

    Decía «exige la ficha técnica, que no está cargada» con la ficha cargada. El
    motivo tiene que ser el real (7-oct).
    """
    r = compare(
        [declarado(fraction_code="73051291", nico_code="99")],
        [esperado(fraction_code="73051291", nico_code=None, valid_nico_codes=("00", "99"))],
    )

    assert not [x for x in r.divergences if x.kind is DivergenceType.NICO_MISMATCH]
    assert any("clasificación que llegue hasta el NICO" in m for m in r.unverifiable)
    assert not any("no está cargada" in m for m in r.unverifiable)


def test_si_la_fraccion_no_esta_vigente_no_se_acusa_al_nico() -> None:
    """Decir «no existe» sería culpar al pedimento de un hueco del catálogo."""
    r = compare([declarado(nico_code="99")], [esperado(nico_code=None, valid_nico_codes=None)])

    assert not [x for x in r.divergences if x.kind is DivergenceType.NICO_MISMATCH]
    assert any("no está vigente en la tarifa" in m for m in r.unverifiable)


def test_una_fraccion_sin_nico_cargados_tampoco_permite_acusar() -> None:
    r = compare([declarado(nico_code="99")], [esperado(nico_code=None, valid_nico_codes=())])

    assert not [x for x in r.divergences if x.kind is DivergenceType.NICO_MISMATCH]
    assert any("hueco del catálogo, no del pedimento" in m for m in r.unverifiable)


def test_una_partida_que_se_contradice_a_si_misma_se_delata() -> None:
    """El valor impreso no cuadra con precio pagado más incrementables.

    Es detección a nivel de partida: no mira el encabezado ni el DTA.
    """
    r = compare(
        [declarado(customs_value=Decimal("196032.83"))],
        [esperado(customs_value=Decimal("181511.88"))],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.VALUE_MISMATCH)
    assert d.declared_value == "196032.83"
    assert d.expected_value == "181511.88"


def test_sin_precio_pagado_el_valor_no_se_da_por_bueno() -> None:
    r = compare([declarado()], [esperado(customs_value=None)])

    assert not [x for x in r.divergences if x.kind is DivergenceType.VALUE_MISMATCH]
    assert any("precio pagado" in m for m in r.unverifiable)


def test_el_nico_inexistente_se_reporta_aunque_no_se_pudiera_clasificar() -> None:
    """No se apoya en la clasificación: sale del catálogo y de lo declarado.

    Antes se descartaba junto con la fracción cuando el motor no llegaba a una
    clasificación defendible, que es justo el caso de las partidas sin producto
    ligado.
    """
    r = compare(
        [declarado(fraction_code="73241001", nico_code="99")],
        [
            esperado(
                is_resolved=False,
                fraction_code=None,
                nico_code=None,
                valid_nico_codes=("00",),
            )
        ],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.NICO_MISMATCH)
    assert "no existe en la fracción 73241001" in d.reasoning


# ── Las tres comprobaciones deterministas (Persona 1, 22-sep) ──────────────


def test_el_igi_se_comprueba_contra_la_tarifa_de_la_fraccion_declarada() -> None:
    """No hace falta clasificar: aunque la fracción esté mal, el importe tiene
    que cuadrar con la tasa de la que se declaró."""
    r = compare(
        [declarado(igi_amount=Decimal("6917.52"))],
        [esperado(igi_amount=Decimal("9684.52"))],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.IGI_RATE_MISMATCH)
    assert d.severity == "CRITICAL", "cambia lo que se paga"
    assert d.declared_value == "6917.52"
    assert d.expected_value == "9684.52"


def test_el_iva_se_comprueba_contra_su_base() -> None:
    r = compare(
        [declarado(vat_amount=Decimal("23775.04"))],
        [esperado(vat_amount=Decimal("23638.04"))],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.VAT_MISMATCH)
    assert "no cuadra con su base" in d.reasoning
    assert "no se distingue" in d.reasoning, "no se afirma si fue la base o el importe"


def test_una_diferencia_de_centavos_es_redondeo_y_no_un_hallazgo() -> None:
    r = compare(
        [declarado(igi_amount=Decimal("9684.53"))],
        [esperado(igi_amount=Decimal("9684.52"))],
    )

    assert not [x for x in r.divergences if x.kind is DivergenceType.IGI_RATE_MISMATCH]


def test_una_unidad_que_no_existe_en_el_anexo_22_es_hallazgo() -> None:
    r = compare(
        [declarado(unit="99")],
        [esperado(declared_unit_is_known=False)],
    )

    d = next(x for x in r.divergences if x.kind is DivergenceType.UNIT_MISMATCH)
    assert d.declared_value == "99"
    assert d.expected_value is None, "no se inventa cuál era la correcta"
    assert "Apéndice 7" in d.reasoning


def test_sin_catalogo_de_unidades_no_se_acusa_a_la_partida() -> None:
    """Un hueco del catálogo no es un error del pedimento."""
    r = compare([declarado(unit="99")], [esperado(declared_unit_is_known=None)])

    assert not [x for x in r.divergences if x.kind is DivergenceType.UNIT_MISMATCH]
    assert any("no se consultó el" in m for m in r.unverifiable)


def test_sin_tasa_en_el_catalogo_el_igi_no_se_da_por_bueno() -> None:
    r = compare([declarado()], [esperado(igi_amount=None, vat_amount=None)])

    assert not [x for x in r.divergences if x.kind is DivergenceType.IGI_RATE_MISMATCH]
    assert any("no se pudo comprobar el IGI" in m for m in r.unverifiable)
    assert any("no se pudo comprobar el IVA" in m for m in r.unverifiable)


def test_toda_divergencia_tiene_etiqueta_en_la_interfaz() -> None:
    """La pantalla no puede quedarse callada sobre un hallazgo que el motor emite.

    Cruza el vocabulario del §18 con las etiquetas del frontend: si alguien
    añade un tipo y no lo nombra allí, la pantalla mostraría la constante en
    crudo a un agente aduanal. Se comprueba desde aquí porque el frontend no
    tiene runner de tests.
    """
    import pathlib

    etiquetas = pathlib.Path("apps/web/src/components/divergencias.ts").read_text()

    for tipo in DivergenceType:
        assert f"{tipo.value}: {{" in etiquetas, f"falta la etiqueta de {tipo.value}"


# ── Ficha técnica incompleta ─────────────────────────────────────────────────


def test_una_ficha_a_la_que_le_falta_un_dato_es_un_hallazgo() -> None:
    """El caso del corpus: la ficha no trae la descripción técnica."""
    r = compare([declarado()], [esperado(missing_technical_fields=("descripcion_tecnica",))])

    (d,) = r.divergences
    assert d.kind is DivergenceType.MISSING_TECHNICAL_FIELD
    assert d.expected_value == "descripcion_tecnica"
    assert d.severity == "MEDIUM"


def test_el_hallazgo_no_acusa_al_que_declaro() -> None:
    """Dice que el expediente no alcanza, no que el pedimento esté mal.

    La diferencia no es de tono: una acusación se contesta corrigiendo el
    pedimento, y esto se arregla pidiéndole la ficha al proveedor.
    """
    r = compare([declarado()], [esperado(missing_technical_fields=("composicion",))])

    (d,) = r.divergences
    assert d.declared_value is None, "no hay nada declarado que esté mal"
    assert "proveedor" in d.reasoning


def test_una_ficha_completa_no_produce_nada() -> None:
    r = compare([declarado()], [esperado(missing_technical_fields=())])

    assert not r.has_findings
    assert r.is_complete


def test_una_ficha_que_no_se_consulto_no_pasa_por_limpia() -> None:
    """`None` es lo que traen las partidas sin producto ligado.

    Sin esta distinción, no haber mirado la ficha se vería igual que haberla
    mirado y encontrarla completa — que es la forma más fácil de inflar un
    recall.
    """
    r = compare([declarado()], [esperado(missing_technical_fields=None)])

    assert not r.has_findings
    assert not r.is_complete
    assert any("no se consultó la ficha técnica" in m for m in r.unverifiable)


def test_se_señala_aunque_la_clasificacion_no_se_sostenga() -> None:
    """Es el caso NORMAL, no el raro: suele ser la razón de que no se sostenga.

    Si el detector dependiera de `is_resolved`, callaría justo cuando más falta
    hace — en las partidas que nadie pudo clasificar por culpa de la ficha.
    """
    r = compare(
        [declarado()],
        [
            esperado(
                is_resolved=False,
                fraction_code=None,
                missing_technical_fields=("descripcion_tecnica",),
            )
        ],
    )

    tipos = {d.kind for d in r.divergences}
    assert DivergenceType.MISSING_TECHNICAL_FIELD in tipos


def test_la_metrica_ya_no_cuenta_este_tipo_como_detector_inexistente() -> None:
    """Persona 2 corrigió el corpus el 22-sep; el detector existe desde hoy."""
    from core.evaluation.deteccion import DETECTOR_POR_ERROR, SIN_DETECTOR

    assert "MISSING_TECHNICAL_FIELD" not in SIN_DETECTOR
    assert DETECTOR_POR_ERROR["MISSING_TECHNICAL_FIELD"] == "MISSING_TECHNICAL_FIELD"


# ── Los motivos tienen que ser los de hoy (7-oct) ──────────────────────────


def test_sin_fraccion_esperada_las_nom_no_se_atribuyen_a_un_catalogo_que_falta() -> None:
    """Decía «falta cargar la correlación fracción → NOM» con 456 cargadas."""
    from core.shadow.compare import _lagunas
    from core.shadow.types import ExpectedItem

    sin_fraccion = ExpectedItem(line_number=1, fraction_code=None, required_nom_codes=None)
    razones = _lagunas(sin_fraccion, None)

    assert any("no llegó a una fracción esperada" in r for r in razones)
    assert not any("falta cargar" in r for r in razones)


def test_los_identificadores_no_se_atribuyen_al_apendice_8() -> None:
    """El catálogo está cargado: lo que falta son las reglas que dicen cuáles exige."""
    from core.shadow.compare import _lagunas
    from core.shadow.types import ExpectedItem

    razones = _lagunas(ExpectedItem(line_number=1, required_identifiers=None), None)

    assert any("reglas de la RGCE" in r for r in razones)
    assert not any("falta cargar el Apéndice 8" in r for r in razones)
