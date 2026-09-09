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
            reform_note=None,
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
        ("ARTICULO 167-G. Texto.", "167-G"),
        ("ARTICULO 9o. Texto.", "9"),
        ("ARTICULO 9o.-A. Texto.", "9-A"),
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


def test_parse_articles_vigente_sin_nota_de_articulo_usa_la_mas_reciente_de_cualquier_nivel() -> (
    None
):
    """Regresión real (hallazgo de Persona 3, 2026-09-08, artículo 36-A):

    La mayoría de las reformas tocan un párrafo o un inciso, no "el artículo"
    completo — 36-A real nunca trae una nota que empiece con "Artículo", sólo
    "Párrafo reformado…"/"Inciso reformado…". Antes de este fix, eso hacía que
    `valid_from_override` quedara en `None` y el llamador usara la fecha de
    la última reforma del DOCUMENTO completo (2025-11-19) para un artículo
    que llevaba reformándose desde 2018 — 259 de 274 artículos reales caían
    en este caso.
    """
    lines = _lines(
        "   ARTICULO 36-A. Texto del artículo.\n"
        "                                     Párrafo reformado DOF 25-06-2018\n"
        "                                     Inciso reformado DOF 01-06-2019"
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].valid_from_override == date(2019, 6, 1)  # la MÁS reciente, no la primera
    assert articulos[0].valid_to is None


def test_parse_articles_vigente_con_varias_fechas_en_nota_de_articulo_usa_la_mas_reciente() -> None:
    """Regresión real (artículo 37): "Artículo reformado DOF 09-04-2012,
    09-12-2013" — vigente, no derogado. El texto guardado es el actual, así
    que rige desde la reforma más reciente (2013), no desde 2012."""
    lines = _lines(
        "   ARTICULO 37. Texto.\n                    Artículo reformado DOF 09-04-2012, 09-12-2013"
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].valid_from_override == date(2013, 12, 9)
    assert articulos[0].valid_to is None


def test_parse_articles_sin_ninguna_nota_no_tiene_valid_from_override() -> None:
    """Un artículo que nunca se ha tocado desde que se promulgó la ley no
    trae ninguna nota — el respaldo (la fecha de publicación original) lo
    decide el llamador, no el parser."""
    lines = _lines("   ARTICULO 1o. Texto que nunca se ha reformado.")

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].valid_from_override is None


def test_parse_articles_reform_note_deja_la_vigencia_verificable() -> None:
    """Hallazgo real de Persona 3 (2026-09-08): sin esto, una fila puede decir
    que rige desde una fecha sin que su `text` contenga nada que lo explique.
    `reform_note` guarda la nota tal como aparece en el documento, aparte del
    cuerpo del artículo."""
    lines = _lines(
        "   ARTICULO 36-A. Texto del artículo.\n"
        "                                     Párrafo reformado DOF 25-06-2018\n"
        "                                     Inciso reformado DOF 01-06-2019"
    )

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].reform_note == (
        "Párrafo reformado DOF 25-06-2018; Inciso reformado DOF 01-06-2019"
    )
    assert "reformad" not in articulos[0].text.lower()


def test_parse_articles_sin_notas_reform_note_es_none() -> None:
    lines = _lines("   ARTICULO 1o. Texto que nunca se ha reformado.")

    articulos = ley_aduanera.parse_articles(lines)

    assert articulos[0].reform_note is None


def test_parse_articles_no_duplica_ningun_numero() -> None:
    lines = _lines(
        "ARTICULO 1o. Uno.\nARTICULO 2o. Dos.\nARTICULO 9o. Nueve.\nARTICULO 9o.-A. Nueve A."
    )

    articulos = ley_aduanera.parse_articles(lines)

    numeros = [a.rule_number for a in articulos]
    assert len(numeros) == len(set(numeros))
