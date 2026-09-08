"""Tests del parser de la Ley Aduanera (§ Task 4 TAREA_P2).

`unit` — sobre fragmentos de texto que reproducen los patrones reales
verificados contra el PDF de Diputados (texto vigente, última reforma
19-nov-2025): no dependen de la red ni del PDF original.
"""

from __future__ import annotations

from datetime import date

import pytest
from ingestion.diputados import ley_aduanera

pytestmark = pytest.mark.unit


def _lines(text: str) -> list[str]:
    return [line + "\n" for line in text.split("\n")]


def test_parse_articles_extrae_numero_y_texto() -> None:
    lines = _lines("   ARTICULO 2o. Para los efectos de esta Ley se considera algo.")

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos == [
        ley_aduanera.ParsedArticle(
            rule_number="2",
            text="Para los efectos de esta Ley se considera algo.",
            valid_to=None,
            valid_from_override=None,
        )
    ]


def test_parse_articles_junta_continuacion_multilinea() -> None:
    lines = _lines(
        "   ARTICULO 5o. Primer renglón\n"
        "del artículo que continúa\n"
        "en más líneas.\n"
        "\n"
        "   ARTICULO 6o. Otro artículo."
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].rule_number == "5"
    assert "continúa" in articulos[0].text
    assert "en más líneas." in articulos[0].text
    assert articulos[1].rule_number == "6"


@pytest.mark.parametrize(
    ("heading", "esperado"),
    [
        ("ARTICULO 10. Texto.", "10"),
        ("ARTICULO 167-G. Texto.", "167G"),
        ("ARTICULO 9o. Texto.", "9"),
        ("ARTICULO 9o.-A. Texto.", "9A"),
        ("ARTICULO 49 bis. Texto.", "49-BIS"),
        ("ARTICULO 137 bis 1.- Texto.", "137-BIS-1"),
    ],
)
def test_parse_articles_reconoce_las_variantes_reales_de_numeracion(
    heading: str, esperado: str
) -> None:
    articulos = ley_aduanera.parse_articles(_lines(heading))

    assert [a.rule_number for a in articulos] == [esperado]


def test_parse_articles_no_confunde_137_bis_1_con_137_bis_9() -> None:
    """Regresión: el artículo 137 tiene 9 sub-artículos "bis" reales
    (137 bis 1 a 137 bis 9) — deben quedar como filas distintas, no una."""
    lines = _lines("ARTICULO 137 bis 1.- Primero.\nARTICULO 137 bis 9.- Noveno.")

    articulos = ley_aduanera.parse_articles(lines)

    assert [a.rule_number for a in articulos] == ["137-BIS-1", "137-BIS-9"]


def test_parse_articles_ignora_ruido_de_pagina() -> None:
    lines = _lines(
        "   ARTICULO 1o. Texto del artículo.\n"
        "\n"
        "                                                  1 de 220\n"
        "                                                                  LEY ADUANERA\n"
        "              CÁMARA DE DIPUTADOS DEL H. CONGRESO DE LA UNIÓN                    Última Reforma DOF 19-11-2025\n"
        "              Secretaría General\n"
        "              Secretaría de Servicios Parlamentarios\n"
        "\n"
        "   más texto que sigue."
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert len(articulos) == 1
    assert "más texto que sigue." in articulos[0].text
    assert "CÁMARA DE DIPUTADOS" not in articulos[0].text


def test_parse_articles_corta_en_transitorios() -> None:
    lines = _lines(
        "   ARTICULO 203.- Texto del último artículo.\n"
        "\n"
        "                                       Transitorios\n"
        "\n"
        "    Primero. La presente Ley entrará en vigor...\n"
        "   ARTICULO 187. $10,830.00 a $14,890.00"
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert [a.rule_number for a in articulos] == ["203"]


def test_parse_articles_fraccion_derogada_no_cierra_el_articulo() -> None:
    """Regresión (artículo 20 real): una "Fracción derogada" no significa que
    el artículo completo dejó de estar vigente — sólo una parte."""
    lines = _lines(
        "   ARTICULO 20. Texto vigente del artículo.\n"
        "                                        Fracción derogada DOF 09-12-2013\n"
        "\n"
        "   ARTICULO 21. Siguiente artículo."
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].valid_to is None


def test_parse_articles_articulo_derogado_fija_valid_to() -> None:
    lines = _lines(
        "   ARTICULO 44. (Se deroga).\n"
        "                                                     Artículo derogado DOF 09-12-2013"
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].valid_to == date(2013, 12, 9)


def test_parse_articles_derogado_usa_fecha_mas_antigua_como_valid_from() -> None:
    """Regresión: si `valid_from` usara la fecha de la última reforma del
    documento completo (2025-11-19), un artículo derogado antes invertiría
    el intervalo (valid_from > valid_to)."""
    lines = _lines(
        "   ARTICULO 38. Texto.\n"
        "                    Artículo reformado DOF 01-01-2002, 30-12-2002. Derogado DOF 09-12-2013"
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].valid_from_override == date(2002, 1, 1)
    assert articulos[0].valid_to == date(2013, 12, 9)
    assert articulos[0].valid_from_override <= articulos[0].valid_to


def test_parse_articles_derogado_con_nota_compuesta_en_la_misma_linea() -> None:
    """Regresión real (artículo 137 bis 8): la nota final no siempre empieza
    con "Artículo derogado" — puede venir después de otra acción en la misma
    línea ("Artículo adicionado DOF ... Derogado DOF ...")."""
    lines = _lines(
        "   ARTICULO 137 bis 8.- (Derogado).\n"
        "               Artículo adicionado DOF 25-06-2002. Derogado DOF 19-11-2025"
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].valid_to == date(2025, 11, 19)
    assert articulos[0].valid_from_override == date(2002, 6, 25)


def test_parse_articles_no_duplica_ningun_numero() -> None:
    lines = _lines(
        "ARTICULO 1o. Uno.\nARTICULO 2o. Dos.\nARTICULO 9o. Nueve.\nARTICULO 9o.-A. Nueve A."
    )

    articulos = ley_aduanera.parse_articles(lines)

    numeros = [a.rule_number for a in articulos]
    assert len(numeros) == len(set(numeros))
