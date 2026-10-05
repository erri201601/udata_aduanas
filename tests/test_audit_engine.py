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
        "unit": "6",
        "igi_amount": Decimal("15000.00"),
        "vat_amount": Decimal("18528.00"),
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
        # Igual que los identificadores: explícito «se comprobó y cuadra», para
        # que un pedimento limpio se pueda afirmar limpio.
        "igi_amount": Decimal("15000.00"),
        "vat_amount": Decimal("18528.00"),
        "declared_unit_is_known": True,
        # Explícito: se consultó la ficha y está completa. `None` diría que no
        # se consultó, y entonces la partida no se podría afirmar limpia.
        "missing_technical_fields": (),
        "valid_nico_codes": ("00",),
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


# ── Las dos clases de monto (Persona 1, 5-oct) ──────────────────────────────


def test_un_igi_mal_calculado_lleva_su_monto_sin_clasificar() -> None:
    """EL CASO QUE DESBLOQUEA EL DINERO DE LA CONSOLA.

    Un IGI mal calculado no compara tasas: compara lo que el importador
    ESCRIBIÓ contra lo que la ley da para la fracción que él mismo declaró. No
    hace falta clasificar nada para afirmarlo, así que el monto existe aunque
    el motor no haya podido sostener una fracción esperada — que es el caso de
    3 de cada 4 partidas del corpus.

    Mientras dependió del motor fiscal, 199 hallazgos de IGI y 289 de IVA
    salían en la consola como «sin monto» con los dos importes dentro.
    """
    r = auditar(
        comparison=comparacion(
            declarado={"igi_amount": Decimal("4822.95")},
            esperado={"igi_amount": Decimal("14468.85")},
        ),
        # SIN tasas: el motor fiscal no puede cuantificar nada aquí.
        transaction_value=None,
        declared_rates=None,
        expected_rates=None,
    )

    h = next(f for f in r.findings if f.divergence.kind is DivergenceType.IGI_RATE_MISMATCH)
    assert h.impact_amount == Decimal("9645.90"), "la diferencia de los dos importes"
    assert h.impact_direction == "OMISION"
    assert h.is_actionable, "con monto se puede presentar, no sólo investigar"


def test_el_igi_y_el_iva_mal_calculados_se_suman() -> None:
    """Son contribuciones DISTINTAS y se deben las dos.

    Deduplicarlas con un `max()` se quedaría con la mayor y perdería la otra:
    el importador debe el IGI que faltó Y el IVA que faltó.
    """
    r = auditar(
        comparison=comparacion(
            declarado={"igi_amount": Decimal("5000.00"), "vat_amount": Decimal("17000.00")},
            esperado={"igi_amount": Decimal("15000.00"), "vat_amount": Decimal("18528.00")},
        ),
        transaction_value=None,
        declared_rates=None,
        expected_rates=None,
    )

    assert r.total_exposure == Decimal("11528.00"), "10,000 de IGI + 1,528 de IVA"


def test_el_error_de_calculo_no_se_suma_al_delta_de_la_fraccion() -> None:
    """EL TEST QUE CORRIGIÓ LA DECISIÓN ANTES DE QUE SE MERGEARA.

    Parecía que las dos piezas telescopaban y que el total era su suma. Lo
    hacen, pero sólo contribución por contribución: el delta de la fracción
    mide el movimiento de TODAS a la vez y lo mide desde importes
    RECALCULADOS, no desde los escritos.

    Aquí: valor 100 000, tasa declarada 0.05, correcta 0.15, IGI escrito 1 000
    e IVA escrito 18 528. Sumar daba **15 600**; lo que se debe son **13 872**,
    porque el delta de la fracción ya trae el arrastre del IVA (16 800 a
    18 400) medido contra un IVA que nadie escribió, y el escrito estaba 128
    por encima.

    Así que no se suman. La partida reporta su error de cálculo —exacto, sin
    clasificar— y la fracción queda dicha aparte. Se reporta DE MENOS a
    propósito: un importe que mezcla dos bases no se sostiene delante de una
    autoridad.
    """
    r = auditar(
        comparison=comparacion(
            declarado={"fraction_code": "84713099", "igi_amount": Decimal("1000.00")},
            esperado={"igi_amount": Decimal("5000.00")},
        ),
        transaction_value=VALOR,
        declared_rates=TASAS_DECLARADAS,
        expected_rates=TASAS_ESPERADAS,
    )

    assert r.total_exposure == Decimal("4000.00"), "el error de cálculo, exacto"
    assert r.total_exposure != Decimal("15600.00"), "nunca la suma de las dos bases"
    # Y la fracción sigue ahí, con su delta, para que se pueda decir que puede
    # mover más: lo que no hace es entrar en el total.
    fraccion = next(f for f in r.findings if f.divergence.kind is DivergenceType.FRACTION_MISMATCH)
    assert fraccion.impact_amount == Decimal("11600.00")


def test_las_causas_siguen_sin_contarse_dos_veces() -> None:
    """La regla vieja no se afloja: fracción y origen explican el MISMO delta.

    Es el test de arriba —`test_el_total_no_cuenta_el_mismo_dinero_dos_veces`—
    visto desde el alcance: las dos llevan `LINEA_COMPLETA` y el total toma
    una, no las suma.
    """
    from core.audit import ALCANCE_LINEA

    r = auditar(
        comparison=comparacion(
            declarado={"fraction_code": "84713099", "country_of_origin": "US"},
            esperado={"country_of_origin": "CN"},
        )
    )

    cuantificados = [f for f in r.findings if f.impact_amount is not None]
    assert {f.impact_scope for f in cuantificados} == {ALCANCE_LINEA}
    assert r.total_exposure == Decimal("11600.00"), "una, no la suma de las dos"


def test_un_importe_que_no_es_numero_no_se_fuerza_a_cero() -> None:
    """Un campo que no es dinero no tiene delta.

    Convertirlo a cero lo presentaría como «comprobado y sin diferencia», que
    es la mentira que este proyecto persigue en todas sus formas.
    """
    from core.audit.engine import _error_de_calculo
    from core.shadow import Divergence

    d = Divergence(
        kind=DivergenceType.IGI_RATE_MISMATCH,
        line_number=1,
        field="igi_amount",
        declared_value="sin dato",
        expected_value="14468.85",
        severity="CRITICAL",
        reasoning="x",
    )
    assert _error_de_calculo(d) is None


def test_el_motor_escribe_importes_en_los_dos_tipos_por_contribucion() -> None:
    """EL CONTRATO CON `core/shadow/compare.py`.

    `_error_de_calculo` resta `expected_value` menos `declared_value` y los
    trata como dinero. El tipo se llama `IGI_RATE_MISMATCH` —por historia— y si
    alguien lo emitiera comparando TASAS en vez de importes, el delta saldría
    en céntimos y la consola presentaría 0.10 pesos como la deuda.

    Se comprueba contra el motor de verdad, no contra una cadena escrita a
    mano: si el campo cambia de significado, esto falla en vez de que el
    importe se vuelva absurdo en silencio.
    """
    from decimal import InvalidOperation

    from core.audit import POR_CONTRIBUCION

    r = auditar(
        comparison=comparacion(
            declarado={"igi_amount": Decimal("4822.95"), "vat_amount": Decimal("16328.58")},
            esperado={"igi_amount": Decimal("14468.85"), "vat_amount": Decimal("17871.92")},
        ),
        transaction_value=None,
        declared_rates=None,
        expected_rates=None,
    )

    por_contribucion = [f for f in r.findings if f.divergence.kind in POR_CONTRIBUCION]
    assert len(por_contribucion) == 2, "IGI e IVA, los dos tipos"
    for f in por_contribucion:
        assert f.divergence.field in {"igi_amount", "vat_amount"}, (
            f"{f.divergence.kind} ya no compara un importe: {f.divergence.field}"
        )
        for valor in (f.divergence.declared_value, f.divergence.expected_value):
            try:
                importe = Decimal(valor or "")
            except InvalidOperation:  # pragma: no cover - es el fallo que se vigila
                pytest.fail(f"{f.divergence.kind} escribió algo que no es dinero: {valor!r}")
            assert importe > 1, "una tasa (0.15) no es un importe: el campo cambió de sentido"


def test_todo_lo_que_el_hallazgo_mapea_llega_a_la_tabla() -> None:
    """EL TEST QUE CAZA UNA FAMILIA ENTERA DE DEFECTOS.

    `impact_scope` se calculó en el motor, viajó en `to_finding_fields()` y el
    repositorio —que construye la fila con campos nombrados uno a uno— no lo
    incluía. El importe se guardaba bien y la INSTRUCCIÓN DE CÓMO AGREGARLO se
    perdía: el agregador leía el nulo como «delta entero de la partida» y
    deduplicaba con un máximo dos contribuciones que se deben las dos. La fila
    quedaba bien y el total mal.

    Es la sexta vez en este proyecto que un campo se escribe en el dominio y
    nadie lo lee de vuelta —`document_ref`, `data_origin`, la vigencia,
    `rule_id`/`prompt_id`, `input_kinds`—. Este test no comprueba un campo:
    comprueba que NINGUNO de los que el hallazgo mapea se quede por el camino.
    """
    import inspect

    from database.models import RiskFinding
    from database.repositories.review import save_review

    campos = (
        auditar(
            comparison=comparacion(
                declarado={"fraction_code": "84713099", "igi_amount": Decimal("1000.00")},
                esperado={"igi_amount": Decimal("5000.00")},
            ),
            transaction_value=VALOR,
            declared_rates=TASAS_DECLARADAS,
            expected_rates=TASAS_ESPERADAS,
        )
        .findings[0]
        .to_finding_fields()
    )

    columnas = {c.name for c in RiskFinding.__table__.columns}
    fuente = inspect.getsource(save_review)

    perdidos = [nombre for nombre in campos if nombre in columnas and f"{nombre}=" not in fuente]
    assert perdidos == [], (
        f"el hallazgo mapea {perdidos} y `save_review` no los pasa: se calculan y se tiran"
    )
