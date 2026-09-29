"""Tests de `ingestion.dof.anexo22.parse_identifiers` (Apéndice 8) contra un
fragmento real del Anexo 22 RGCE 2026."""

from __future__ import annotations

import pytest
from ingestion.dof.anexo22 import ParsedIdentifier, parse_identifiers

from tests.fixtures.anexo22_apendice8_fragmento import APENDICE_8_FRAGMENTO

pytestmark = pytest.mark.unit


def test_encuentra_las_entradas_normales_con_nivel() -> None:
    identificadores = parse_identifiers(APENDICE_8_FRAGMENTO)

    normales = {i.code: i.level for i in identificadores if i.code in ("AC", "AE", "AF", "AG")}
    assert normales == {"AC": "G", "AE": "G", "AF": "G", "AG": "G"}


def test_no_confunde_el_encabezado_de_columnas_con_una_entrada() -> None:
    identificadores = parse_identifiers(APENDICE_8_FRAGMENTO)

    assert "Clave" not in [i.code for i in identificadores]


def test_no_confunde_la_lista_jerarquica_del_complemento_con_entradas_nuevas() -> None:
    """El "Complemento 1" de AI trae "1. No aplica. 2. Ley Aduanera: a)... b)
    Otros. 3. IGI: a) Carne de pollo..." -- ninguno de esos incisos/numerales
    debe leerse como un código de identificador nuevo."""
    identificadores = parse_identifiers(APENDICE_8_FRAGMENTO)

    assert ParsedIdentifier(code="AI", level="G") in identificadores
    codigos = [i.code for i in identificadores]
    assert len(codigos) == len(set(codigos)) + 0  # sin duplicados espurios de esta lista
    assert "AC" in codigos  # la letra "AC" reaparece dentro del texto de AI, no como código nuevo
    assert codigos.count("AC") == 1


def test_una_entrada_sin_columna_nivel_queda_con_level_none() -> None:
    """10 de las 174 entradas reales no traen G/P -- A1 es una de ellas."""
    identificadores = parse_identifiers(APENDICE_8_FRAGMENTO)

    assert ParsedIdentifier(code="A1", level=None) in identificadores


def test_el_ruido_institucional_no_produce_entradas() -> None:
    identificadores = parse_identifiers(APENDICE_8_FRAGMENTO)

    codigos = [i.code for i in identificadores]
    assert "DI" not in codigos  # de "DIARIO OFICIAL" -- ya filtrado por _NOISE_RE


def test_total_de_entradas_del_fragmento() -> None:
    assert len(parse_identifiers(APENDICE_8_FRAGMENTO)) == 6
