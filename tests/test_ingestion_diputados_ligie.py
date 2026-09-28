"""Tests de `ingestion.diputados.ligie` contra un fragmento real de la LIGIE 2022."""

from __future__ import annotations

import pytest
from ingestion.diputados.ligie import parse_preambulo_y_articulo1

from tests.fixtures.ligie_pagina1_fragmento import PAGINA_1_LIGIE

pytestmark = pytest.mark.unit


def _lineas() -> list[str]:
    return PAGINA_1_LIGIE.splitlines()


def test_devuelve_preambulo_y_articulo1_en_ese_orden() -> None:
    resultado = parse_preambulo_y_articulo1(_lineas())
    assert [r.rule_number for r in resultado] == ["PREAMBULO", "1"]


def test_preambulo_empieza_en_el_sello_y_termina_en_articulo_unico() -> None:
    preambulo = parse_preambulo_y_articulo1(_lineas())[0]
    assert preambulo.text.startswith("Al margen un sello con el Escudo Nacional")
    assert preambulo.text.endswith(
        "Artículo Único. Se expide la Ley de los Impuestos Generales de "
        "Importación y de Exportación"
    )


def test_preambulo_no_arrastra_el_encabezado_institucional_repetido() -> None:
    """El encabezado ("LEY DE LOS IMPUESTOS...", "CÁMARA DE DIPUTADOS...",
    "TEXTO VIGENTE"...) se repite en cada página -- no es parte del decreto."""
    preambulo = parse_preambulo_y_articulo1(_lineas())[0]
    assert "CÁMARA DE DIPUTADOS" not in preambulo.text
    assert "TEXTO VIGENTE" not in preambulo.text


def test_articulo1_texto_completo_verbatim() -> None:
    articulo1 = parse_preambulo_y_articulo1(_lineas())[1]
    assert articulo1.text == (
        "Artículo 1o.- Se establecen las cuotas que, atendiendo a la clasificación "
        "de la mercancía, servirán para determinar los Impuestos Generales de "
        "Importación y de Exportación, de conformidad con la siguiente: TARIFA"
    )


def test_articulo1_no_arrastra_el_cuerpo_de_la_tarifa() -> None:
    """Lo que sigue a "TARIFA" (Sección I, Capítulo 01...) es el cuerpo de la
    tarifa, no el Artículo 1o. -- ya se carga de otra fuente (tariff_headings)."""
    articulo1 = parse_preambulo_y_articulo1(_lineas())[1]
    assert "Sección I" not in articulo1.text
    assert "Capítulo 01" not in articulo1.text
