"""El NICO por medidas (ADR 0016): elige sólo cuando los números deciden.

Los textos son los de la LIGIE vigente, copiados de la base el 20-oct. Lo que
se protege: que no elija si algún NICO habla de algo que no sean medidas, que
no elija sin la medida, que con solapes gane el más específico y, si ninguno lo
es, que no gane nadie.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from core.classification import nico_de
from core.classification.nico_por_medida import (
    Intervalo,
    leer_condiciones,
    medidas_de,
    nico_por_medida,
)

pytestmark = pytest.mark.unit

D = Decimal
HOY = date(2026, 10, 20)

TUBO_LONGITUDINAL = (  # 7305.11.02 y 7305.12.91
    ("01", "Con espesor de pared inferior a 50.8 mm."),
    (
        "02",
        "Con espesor de pared superior o igual a 4.77 mm pero inferior o igual a 25.4 mm, "
        "de diámetro exterior inferior o igual a 1,219.2 mm.",
    ),
    ("99", "Los demás."),
)
CABLE_7_ALAMBRES = (  # 7312.10.05
    ("01", "De diámetro inferior  a 9.53 mm."),
    ("02", "De diámetro superior o igual a 9.53 mm. pero inferior a 25.4 mm."),
    ("99", "Los demás."),
)
CABLE_LOS_DEMAS = (  # 7312.10.99, recortado
    ("04", "Cables plastificados."),
    ("05", "De acero, de diámetro inferior a 12.7 mm (1/2 pulgada)."),
    ("99", "Los demás."),
)


# ── Leer la LIGIE ────────────────────────────────────────────────────────────


def test_lee_un_rango_con_miles_y_dos_medidas() -> None:
    c = leer_condiciones(TUBO_LONGITUDINAL[1][1])
    assert c == {
        "espesor_pared_mm": Intervalo(D("4.77"), True, D("25.4"), True),
        "diametro_exterior_mm": Intervalo(None, True, D("1219.2"), True),
    }


def test_el_punto_tras_mm_no_rompe_el_rango() -> None:
    assert leer_condiciones(CABLE_7_ALAMBRES[1][1]) == {
        "diametro_mm": Intervalo(D("9.53"), True, D("25.4"), False)
    }


@pytest.mark.parametrize(
    "texto",
    [
        "Cables plastificados.",
        "De acero, de diámetro inferior a 12.7 mm (1/2 pulgada).",
        "Ollas de presión.",
        "De diámetro inferior a 3 pulgadas.",
        "De diámetro.",
    ],
)
def test_lo_que_no_es_solo_una_medida_no_se_lee(texto: str) -> None:
    assert leer_condiciones(texto) is None


# ── Elegir ───────────────────────────────────────────────────────────────────


def test_con_solape_gana_el_mas_especifico() -> None:
    """Lo que firmó César en las 16 partidas de tubo longitudinal."""
    nico, motivo = nico_por_medida(
        TUBO_LONGITUDINAL, {"espesor_pared_mm": D("12.7"), "diametro_exterior_mm": D("914.4")}
    )
    assert nico == "02"
    assert "más específico" in motivo


def test_fuera_del_especifico_queda_el_general() -> None:
    nico, _ = nico_por_medida(
        TUBO_LONGITUDINAL, {"espesor_pared_mm": D("30"), "diametro_exterior_mm": D("508")}
    )
    assert nico == "01"


def test_los_demas_solo_si_no_cabe_en_ningun_otro() -> None:
    assert nico_por_medida(CABLE_7_ALAMBRES, {"diametro_mm": D("25.4")})[0] == "99"
    assert nico_por_medida(CABLE_7_ALAMBRES, {"diametro_mm": D("18")})[0] == "02"


def test_el_limite_exacto_respeta_la_inclusion() -> None:
    assert nico_por_medida(CABLE_7_ALAMBRES, {"diametro_mm": D("9.53")})[0] == "02"
    assert nico_por_medida(CABLE_7_ALAMBRES, {"diametro_mm": D("9.52")})[0] == "01"


def test_sin_la_medida_no_se_elige() -> None:
    nico, motivo = nico_por_medida(TUBO_LONGITUDINAL, {"espesor_pared_mm": D("12.7")})
    assert nico is None
    assert "diametro_exterior_mm" in motivo


def test_si_un_nico_habla_de_otra_cosa_no_se_elige() -> None:
    """7312.10.99: «plastificados» no se descarta con un diámetro."""
    nico, motivo = nico_por_medida(CABLE_LOS_DEMAS, {"diametro_mm": D("10")})
    assert nico is None
    assert "04" in motivo


def test_si_ninguno_es_mas_especifico_no_gana_nadie() -> None:
    cruzados = (
        ("01", "De diámetro superior o igual a 10 mm pero inferior a 30 mm."),
        ("02", "De diámetro superior o igual a 20 mm pero inferior a 40 mm."),
    )
    nico, motivo = nico_por_medida(cruzados, {"diametro_mm": D("25")})
    assert nico is None
    assert "ninguno es más específico" in motivo


def test_un_valor_que_no_es_numero_se_omite_no_se_adivina() -> None:
    assert medidas_de(
        [("diametro_mm", "18"), ("espesor_pared_mm", "aprox. 12"), ("uso", "grua")]
    ) == {"diametro_mm": D("18")}


# ── En `nico_de` ─────────────────────────────────────────────────────────────


class ConTextos:
    def __init__(self, textos: tuple[tuple[str, str], ...]) -> None:
        self.textos = textos

    def nicos(self, *, on_date: date, fraction_code: str) -> tuple[str, ...] | None:
        return tuple(c for c, _ in self.textos)

    def nicos_con_texto(
        self, *, on_date: date, fraction_code: str
    ) -> tuple[tuple[str, str], ...] | None:
        return self.textos


def test_nico_de_aplica_la_regla_si_hay_medidas_y_textos() -> None:
    nico, motivo = nico_de(
        ConTextos(CABLE_7_ALAMBRES),
        on_date=HOY,
        fraction_code="73121005",
        medidas={"diametro_mm": D("18")},
    )
    assert nico == "02"
    assert "por medidas" in motivo and "3 NICO" in motivo


def test_nico_de_sin_medidas_sigue_absteniendose() -> None:
    nico, motivo = nico_de(ConTextos(CABLE_7_ALAMBRES), on_date=HOY, fraction_code="73121005")
    assert nico is None
    assert "no se elige sin una regla" in motivo


def test_nico_de_dice_por_que_no_eligio() -> None:
    nico, motivo = nico_de(
        ConTextos(CABLE_LOS_DEMAS),
        on_date=HOY,
        fraction_code="73121099",
        medidas={"diametro_mm": D("10")},
    )
    assert nico is None
    assert "no se elige" in motivo and "Cables plastificados" in motivo


def test_de_la_ficha_solo_cuenta_lo_observado_o_extraido() -> None:
    from core.classification import medidas_de_la_ficha
    from core.product_dna import ExtractedAttribute, ProductDnaDraft

    dna = ProductDnaDraft(
        attributes=(
            ExtractedAttribute(name="diametro_mm", value="18", status="OBSERVED", locator="l1"),
            ExtractedAttribute(name="espesor_pared_mm", value="12.7", status="INFERRED"),
        )
    )
    assert medidas_de_la_ficha(dna) == {"diametro_mm": D("18")}
