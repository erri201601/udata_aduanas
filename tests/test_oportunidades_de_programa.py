"""PROSEC y Regla 8ª en el Opportunity Finder (ADR 0011, §23).

Lo que se protege es lo que el motor NO hace: elegir el sector por el
importador, sumar alternativas como si fueran ahorros distintos, y presentar
como real un ahorro que sale de una tasa sintética.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.opportunity import (
    OpcionDePrograma,
    OpportunityKind,
    build,
    find_opportunities,
    from_programs,
)
from core.opportunity.types import OpportunityReport
from core.review import LineInput, review_pedimento
from core.shadow import DeclaredItem
from core.taxation import Money, TaxRates

pytestmark = pytest.mark.unit

VALOR = Money(amount=Decimal("100000.00"), currency="MXN")
APLICADAS = TaxRates(igi_rate=Decimal("0.15"), iva_rate=Decimal("0.16"))


def prosec(sector: str, tasa: str, **kw: object) -> OpcionDePrograma:
    return OpcionDePrograma(
        kind=OpportunityKind.PROSEC,
        sector_code=sector,
        sector_name=f"Industria {sector}",
        fraction_code="85285901",
        igi_rate=Decimal(tasa),
        **kw,  # type: ignore[arg-type]
    )


def regla_8a(sector: str, tasa: str = "0", **kw: object) -> OpcionDePrograma:
    return OpcionDePrograma(
        kind=OpportunityKind.REGLA_8A,
        sector_code=sector,
        sector_name=f"Industria {sector}",
        fraction_code="98020001",
        igi_rate=Decimal(tasa),
        **kw,  # type: ignore[arg-type]
    )


def oportunidades(
    opciones: list[OpcionDePrograma],
    sectores: set[str] | None,
    **kw: object,
) -> list:  # type: ignore[type-arg]
    return from_programs(
        line_number=1,
        fraction_code="85285901",
        opciones=opciones,
        transaction_value=kw.pop("valor", VALOR),  # type: ignore[arg-type]
        applied_rates=kw.pop("aplicadas", APLICADAS),  # type: ignore[arg-type]
        client_sectors=frozenset(sectores) if sectores is not None else None,
        is_simulation=kw.pop("simulacion", False),  # type: ignore[arg-type]
    )


# ── Sin saber el sector del importador ───────────────────────────────────────


def test_sin_sector_prosec_se_senala_sin_monto_y_con_todos_los_sectores() -> None:
    [o] = oportunidades([prosec("I", "0.05"), prosec("II", "0")], None)
    assert o.kind is OpportunityKind.PROSEC
    assert o.status == "POTENTIAL"
    assert o.estimated_saving is None, "sin sector, cualquier monto sería de un sector elegido"
    assert "sector I" in o.rationale and "sector II" in o.rationale
    assert "No consta en qué sector" in o.rationale


def test_sin_sector_la_regla_8a_no_se_evalua() -> None:
    assert oportunidades([regla_8a("I"), regla_8a("XIX")], None) == []


# ── Con el sector del importador ─────────────────────────────────────────────


def test_con_sector_se_cuantifica_con_la_tasa_de_su_sector() -> None:
    [o] = oportunidades([prosec("I", "0.05"), prosec("II", "0")], {"I"})
    # 15 % → 5 % sobre 100 000: 10 000 de IGI, y el IVA baja con la base.
    assert o.estimated_saving is not None
    assert o.estimated_saving > Decimal("10000")
    assert "sector I" in o.rationale
    assert "sector II" not in o.rationale, "el sector II no es del importador"


def test_si_el_importador_tiene_dos_sectores_se_ofrece_el_mejor_y_no_se_suman() -> None:
    [o] = oportunidades([prosec("I", "0.05"), prosec("II", "0")], {"I", "II"})
    assert "sector II" in o.rationale.split(":")[0], "la mejor es la del 0 %"
    assert "no se suman" in o.rationale


def test_un_sector_que_no_es_del_importador_no_produce_nada() -> None:
    assert oportunidades([prosec("I", "0.05")], {"XIX"}) == []


def test_una_tasa_que_no_ahorra_no_es_oportunidad() -> None:
    assert oportunidades([prosec("I", "0.15"), prosec("II", "0.20")], {"I", "II"}) == []


def test_sin_arancel_aplicado_no_se_sabe_si_hay_ahorro() -> None:
    assert oportunidades([prosec("I", "0")], {"I"}, aplicadas=None) == []


def test_sin_valor_se_ofrece_sin_monto() -> None:
    [o] = oportunidades([prosec("I", "0")], {"I"}, valor=None)
    assert o.estimated_saving is None
    assert "no se cuantifica" in o.rationale


def test_regla_8a_dice_la_fraccion_9802_por_la_que_se_importaria() -> None:
    [o] = oportunidades([regla_8a("I")], {"I"})
    assert o.kind is OpportunityKind.REGLA_8A
    assert "98020001" in o.rationale
    assert o.estimated_saving is not None
    assert "Que la mercancía no esté excluida del beneficio para el sector." in o.conditions


def test_prosec_y_regla_8a_salen_las_dos_como_caminos_distintos() -> None:
    hechas = oportunidades([prosec("I", "0.05"), regla_8a("I")], {"I"})
    assert {o.kind for o in hechas} == {OpportunityKind.PROSEC, OpportunityKind.REGLA_8A}


# ── Acotaciones y procedencia ────────────────────────────────────────────────


def test_una_fraccion_acotada_lleva_la_acotacion_como_condicion() -> None:
    [o] = oportunidades(
        [prosec("I", "0", is_partial=True, scope_note="Únicamente: pantallas planas.")], {"I"}
    )
    assert any("Únicamente: pantallas planas." in c for c in o.conditions)
    assert "acotada" in o.rationale


def test_las_exclusiones_de_la_regla_8a_viajan_como_condicion() -> None:
    [o] = oportunidades([regla_8a("I", scope_note="Excepto capítulo 72.")], {"I"})
    assert any("Excepto capítulo 72." in c for c in o.conditions)


def test_una_tasa_sintetica_hace_simulada_la_oportunidad() -> None:
    [o] = oportunidades([prosec("I", "0", data_origin="SYNTHETIC")], {"I"}, simulacion=False)
    assert o.is_simulation


def test_la_fuente_de_la_tasa_viaja_con_la_oportunidad() -> None:
    [o] = oportunidades([prosec("I", "0", source_ids=("fuente-prosec",))], {"I"})
    assert o.source_ids == ("fuente-prosec",)


def test_toda_oportunidad_de_programa_exige_comprobar_la_inscripcion() -> None:
    [o] = oportunidades([prosec("I", "0")], {"I"})
    assert any("inscrito" in c for c in o.conditions)


# ── El total ─────────────────────────────────────────────────────────────────


def test_el_techo_toma_el_mayor_por_partida_no_la_suma() -> None:
    """Se paga el IGI una vez: dos caminos al mismo ahorro no son dos ahorros."""
    informe = OpportunityReport(
        opportunities=(
            build(
                OpportunityKind.PROSEC, rationale="", line_number=1, estimated_saving=Decimal(100)
            ),
            build(
                OpportunityKind.REGLA_8A, rationale="", line_number=1, estimated_saving=Decimal(150)
            ),
            build(
                OpportunityKind.PROSEC, rationale="", line_number=2, estimated_saving=Decimal(40)
            ),
            build(OpportunityKind.CORRECTION, rationale="", estimated_saving=Decimal(5)),
        )
    )
    assert informe.total_potential == Decimal(195)


# ── Las notas del informe ────────────────────────────────────────────────────


def test_sin_catalogos_el_informe_dice_que_no_se_evaluaron() -> None:
    informe = find_opportunities(programs_evaluated=False)
    assert any("PROSEC, Regla 8ª" in n for n in informe.notes)


def test_con_catalogos_sin_resultado_no_dice_que_no_se_evaluaron() -> None:
    informe = find_opportunities(programs_evaluated=True)
    assert not any("PROSEC, Regla 8ª" in n for n in informe.notes)
    assert any("tratado" in n for n in informe.notes), "las preferencias siguen sin cargar"


def _linea(programas: tuple[OpcionDePrograma, ...] | None) -> LineInput:
    return LineInput(
        declared=DeclaredItem(line_number=1, fraction_code="85285901"),
        transaction_value=VALOR,
        applied_rates=APLICADAS,
        programs=programas,
        is_simulation=False,
    )


def test_la_revision_usa_las_tasas_aplicadas_aunque_no_haya_espejo() -> None:
    revision = review_pedimento([_linea((prosec("I", "0"),))], client_sectors=frozenset({"I"}))
    assert revision.opportunities is not None
    [o] = revision.opportunities.by_kind(OpportunityKind.PROSEC)
    assert o.estimated_saving is not None


def test_la_revision_dice_que_no_consta_el_sector() -> None:
    revision = review_pedimento([_linea((prosec("I", "0"),))])
    assert revision.opportunities is not None
    assert any("No consta en qué sectores" in n for n in revision.opportunities.notes)


def test_la_revision_sin_catalogos_no_inventa_que_se_evaluaron() -> None:
    revision = review_pedimento([_linea(None)], client_sectors=frozenset({"I"}))
    assert revision.opportunities is not None
    assert revision.opportunities.opportunities == ()
    assert any("no se evaluaron" in n for n in revision.opportunities.notes)
