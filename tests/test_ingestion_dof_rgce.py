"""Tests del parser de las RGCE 2026 (Tarea 1, Persona 2).

`unit` — no dependen de la red ni de MinIO. Los fragmentos de
`tests/fixtures/rgce_2026_fragmentos.py` no son texto reteclado: son
recortes literales, por offset, del HTML real ya verificado en
`docs/RECONOCIMIENTO_RGCE_2026.md` (content_hash documentado ahí y en el
propio fixture) — así lo pidió Persona 1 para las reglas con vigencia
especial (2.1.1., 4.6.1. y las 13 del Transitorio Cuarto): una vigencia
inventada aquí es exactamente el bug que ya se cazó en la Ley Aduanera.
"""

from __future__ import annotations

from datetime import date

import pytest
from ingestion.dof import rgce

from tests.fixtures.rgce_2026_fragmentos import REGLAS, TRANSITORIOS

pytestmark = pytest.mark.unit

# Las 13 reglas del Transitorio Cuarto: dependen del transitorio de OTRO
# decreto (reforma a la Ley Aduanera, DOF 19-11-2025) sin fuente almacenada
# con content_hash en este repo — deben quedar `needs_validation`, nunca con
# una fecha puesta a mano.
_REGLAS_TRANSITORIO_CUARTO = (
    "1.6.27",
    "1.6.28",
    "1.6.37",
    "4.2.5",
    "4.2.6",
    "4.2.10",
    "4.2.11",
    "4.2.13",
    "4.2.14",
    "4.2.18",
    "4.2.22",
    "5.5.1",
    "7.3.1",
)


def _documento(*numeros_de_regla: str) -> str:
    """Un HTML de prueba: fragmentos reales de esas reglas + Transitorios real."""
    return "".join(REGLAS[n] for n in numeros_de_regla) + TRANSITORIOS


def test_parse_rule_bodies_extrae_texto_real_de_1_1_1() -> None:
    lines = rgce.extract_lines(REGLAS["1.1.1"])

    reglas = rgce.parse_rule_bodies(lines)

    assert [n for n, _ in reglas] == ["1.1.1"]
    texto = dict(reglas)["1.1.1"]
    assert "el objeto de la presente" in texto
    assert "Resolución es dar a conocer, agrupar y facilitar" in texto


def test_parse_rules_regla_sin_mencion_en_transitorios_usa_vigencia_del_documento() -> None:
    """1.1.1. no aparece en ningún Transitorio: rige por el Transitorio
    Primero, textual — "entrará en vigor el 1o. de enero de 2026 y estará
    vigente hasta el 31 de diciembre de 2026."."""
    reglas = rgce.parse_rules(_documento("1.1.1"))

    assert len(reglas) == 1
    regla = reglas[0]
    assert regla.valid_from == date(2026, 1, 1)
    assert regla.valid_to == date(2026, 12, 31)
    assert regla.needs_validation is False


@pytest.mark.parametrize("numero", ["2.1.1", "4.6.1"])
def test_parse_rules_2_1_1_y_4_6_1_entran_el_2_de_febrero(numero: str) -> None:
    """Regresión (Transitorio Tercero, texto real): "Las reglas 2.1.1. y
    4.6.1. ... entrarán en vigor el 2 de febrero de 2026." — distinto del
    1o. de enero del resto del cuerpo."""
    reglas = rgce.parse_rules(_documento(numero))

    assert len(reglas) == 1
    regla = reglas[0]
    assert regla.valid_from == date(2026, 2, 2)
    assert regla.valid_to == date(2026, 12, 31)
    assert regla.needs_validation is False


@pytest.mark.parametrize("numero", _REGLAS_TRANSITORIO_CUARTO)
def test_parse_rules_las_13_reglas_del_transitorio_cuarto_quedan_needs_validation(
    numero: str,
) -> None:
    """Regresión (Transitorio Cuarto, texto real): esas 13 reglas entran "en
    términos del transitorio Primero, fracción II del Decreto ... publicado
    en el DOF el 19 de noviembre de 2025" — un decreto que NO es una fuente
    almacenada con content_hash en este repo. Nunca se les pone 2026-01-01
    ni ninguna otra fecha: se marcan y se excluyen de la carga."""
    reglas = rgce.parse_rules(_documento(numero))

    assert len(reglas) == 1
    regla = reglas[0]
    assert regla.valid_from is None
    assert regla.valid_to is None
    assert regla.needs_validation is True
    assert regla.needs_validation_reason is not None
    assert "19-11-2025" in regla.needs_validation_reason
    assert "Ley Aduanera" in regla.needs_validation_reason


def test_parse_rules_documento_completo_de_fixtures_no_mezcla_ninguna_vigencia() -> None:
    """Las 16 reglas de fixture juntas: cada una con la vigencia que le toca,
    ninguna se cuela en la vigencia de otra."""
    todas = tuple(REGLAS.keys())
    reglas = rgce.parse_rules(_documento(*todas))

    por_numero = {r.rule_number: r for r in reglas}
    assert set(por_numero) == set(todas)

    assert por_numero["1.1.1"].valid_from == date(2026, 1, 1)
    assert por_numero["2.1.1"].valid_from == date(2026, 2, 2)
    assert por_numero["4.6.1"].valid_from == date(2026, 2, 2)
    for numero in _REGLAS_TRANSITORIO_CUARTO:
        assert por_numero[numero].needs_validation is True


def test_parse_rules_falla_si_hay_numeros_de_regla_duplicados() -> None:
    """Un extractor que "se las arregla" con datos irregulares produce datos
    incorrectos en silencio (regla 7 CLAUDE.md) — falla ruidoso en vez."""
    html_con_duplicado = REGLAS["1.1.1"] + REGLAS["1.1.1"] + TRANSITORIOS

    with pytest.raises(ValueError, match="duplicad"):
        rgce.parse_rules(html_con_duplicado)


def test_parse_rule_bodies_no_confunde_codigo_de_fraccion_con_encabezado_de_regla() -> None:
    """Regresión real: el documento cita códigos de fracción arancelaria en
    negritas dentro de alguna regla (p. ej. "9901.00.11."), que calzan el
    mismo patrón N.N.N. que un encabezado de regla. Los 7 Títulos reales
    nunca pasan de un dígito; un código de fracción sí (4 dígitos)."""
    html = (
        "<div><span style='font-weight:bold;'>1.1.1.</span>"
        "<span> Texto de la regla uno.</span></div>"
        "<div><span style='font-weight:bold;'>9901.00.11.</span>"
        "<span> esto es una cita de fracción, no un encabezado</span></div>"
    )

    reglas = rgce.parse_rule_bodies(rgce.extract_lines(html))

    assert [n for n, _ in reglas] == ["1.1.1"]
    assert "9901.00.11" in dict(reglas)["1.1.1"]


def test_parse_transitorios_se_queda_con_la_primera_aparicion_de_cada_ordinal() -> None:
    """Regresión real: la nota del DOF trae un SEGUNDO bloque
    "Primero./Segundo./Tercero." más adelante en el mismo HTML, de otro
    instrumento (no de las RGCE), antes de llegar al Anexo 13. Si se
    sobreescribiera con la última aparición, el Transitorio Primero real
    —el que fija la vigencia de las 550 reglas— quedaría reemplazado."""
    lines = rgce.extract_lines(TRANSITORIOS)

    transitorios = rgce.parse_transitorios(lines)

    primero = transitorios["PRIMERO"]
    assert "entrará en vigor el 1o. de enero de 2026" in primero
    assert "31 de marzo de 2026" not in primero  # texto del segundo bloque, bogus


def test_reglas_citadas_extrae_las_dos_del_transitorio_tercero() -> None:
    lines = rgce.extract_lines(TRANSITORIOS)
    transitorios = rgce.parse_transitorios(lines)

    assert rgce.reglas_citadas(transitorios["TERCERO"]) == ["2.1.1", "4.6.1"]


def test_reglas_citadas_extrae_las_13_del_transitorio_cuarto() -> None:
    lines = rgce.extract_lines(TRANSITORIOS)
    transitorios = rgce.parse_transitorios(lines)

    assert tuple(rgce.reglas_citadas(transitorios["CUARTO"])) == _REGLAS_TRANSITORIO_CUARTO
