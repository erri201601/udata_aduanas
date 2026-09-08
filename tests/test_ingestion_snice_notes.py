"""Tests del parser de notas de Sección y Capítulo de la LIGIE.

`unit` — sobre fragmentos de texto que reproducen la estructura real
verificada contra el PDF (encabezado centrado, bloque "Notas.", fin de nota
marcado por la primera fila de partida en columna 0).
"""

from __future__ import annotations

import pytest
from ingestion.snice import notes

pytestmark = pytest.mark.unit


def _lines(text: str) -> list[str]:
    return [line + "\n" for line in text.split("\n")]


def test_parse_notes_extrae_bloque_de_capitulo() -> None:
    lines = _lines(
        "                                                         Capítulo 84.\n"
        "   Reactores nucleares, calderas, máquinas.\n"
        "\n"
        "Notas.\n"
        "\n"
        "    1.   Este Capítulo no comprende:\n"
        "\n"
        "         a)    las muelas del Capítulo 68;\n"
        "\n"
        "84.01\n"
        "8401.10        -      Reactores nucleares."
    )

    parsed = notes.parse_notes(lines)

    assert len(parsed) == 1
    assert parsed[0].path == "Capítulo 84"
    assert parsed[0].rule_number == "NOTAS-CAP-84"
    assert "muelas del Capítulo 68" in parsed[0].text
    assert "84.01" not in parsed[0].text  # la tabla no es parte de la nota


def test_parse_notes_ignora_pie_de_pagina() -> None:
    lines = _lines(
        "                                                         Capítulo 84.\n"
        "Notas.\n"
        "    1.   Primera parte de la nota\n"
        "\n"
        "               Calle Pachuca #189, Col. Condesa, C.P. 06140, Cuauhtémoc, CDMX.   Tel: (55) 5729 9100\n"
        "                                               Dirección General de Facilitación\n"
        "                                               Comercial y de Comercio Exterior\n"
        "         que continúa después del pie de página.\n"
        "\n"
        "84.01"
    )

    parsed = notes.parse_notes(lines)

    assert "Calle Pachuca" not in parsed[0].text
    assert "Primera parte" in parsed[0].text
    assert "continúa después" in parsed[0].text


def test_parse_notes_capitulo_sin_notas_no_genera_fila() -> None:
    lines = _lines(
        "                                                         Capítulo 1.\n"
        "01.01\n"
        "0101.10        -      Caballos."
    )

    parsed = notes.parse_notes(lines)

    assert parsed == []


def test_parse_notes_seccion_y_capitulo_por_separado() -> None:
    lines = _lines(
        "                                                         Sección XVI.\n"
        "MÁQUINAS Y APARATOS\n"
        "Notas.\n"
        "    1.   Esta Sección no comprende algo.\n"
        "\n"
        "                                                         Capítulo 84.\n"
        "Notas.\n"
        "    1.   Este Capítulo no comprende otra cosa.\n"
        "\n"
        "84.01"
    )

    parsed = notes.parse_notes(lines)

    assert [(p.path, p.rule_number) for p in parsed] == [
        ("Sección XVI", "NOTAS-SEC-XVI"),
        ("Capítulo 84", "NOTAS-CAP-84"),
    ]
    assert "Esta Sección" in parsed[0].text
    assert "Este Capítulo" in parsed[1].text


def test_parse_notes_solo_la_primera_aparicion_de_un_capitulo_cuenta() -> None:
    """Regresión: algunos números de capítulo se repiten en el documento real
    (índices, referencias cruzadas) — sólo el primer encabezado real abre un
    bloque de notas propio."""
    lines = _lines(
        "                                                         Capítulo 90.\n"
        "Notas.\n"
        "    1.   Notas verdaderas del capítulo 90.\n"
        "\n"
        "90.01\n"
        "                                                         Capítulo 90.\n"
        "Notas.\n"
        "    1.   Un duplicado que no debe generar una segunda fila.\n"
        "\n"
        "90.02"
    )

    parsed = notes.parse_notes(lines)

    assert len(parsed) == 1
    assert "Notas verdaderas" in parsed[0].text
