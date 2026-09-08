"""Tests del parser del Anexo 22 (catálogos de referencia, §3 TAREA_P2).

`unit` — sobre fragmentos de texto que reproducen los patrones reales
verificados contra el PDF del DOF (15-ene-2026): no dependen de la red ni del
PDF original, que no vive en el repositorio.
"""

from __future__ import annotations

import pytest
from ingestion.dof import anexo22

pytestmark = pytest.mark.unit


def _lines(text: str) -> list[str]:
    """`text` con indentación literal -> lista de líneas con salto final, como
    `readlines()`. Evita que un editor recorte espacios finales importantes."""
    return [line + "\n" for line in text.split("\n")]


# ── find_appendix_headings / appendix_block ─────────────────────────────────


def test_find_appendix_headings_ubica_cada_numero_una_vez() -> None:
    lines = _lines(
        "\n".join(
            [
                "                    Apéndice 1",
                "  01     0     Acapulco.",
                "                    Apéndice 2",
                "A1  -  Importación o exportación definitiva.",
            ]
        )
    )

    headings = anexo22.find_appendix_headings(lines)

    assert headings == {1: 0, 2: 2}


def test_appendix_block_excluye_la_linea_de_encabezado() -> None:
    lines = _lines("Apéndice 1\ncontenido\nApéndice 2\notro")
    headings = anexo22.find_appendix_headings(lines)

    bloque = anexo22.appendix_block(lines, headings, 1)

    assert bloque == ["contenido\n"]


def test_appendix_block_apendice_inexistente_falla_ruidoso() -> None:
    lines = _lines("Apéndice 1\ncontenido")
    headings = anexo22.find_appendix_headings(lines)

    with pytest.raises(RuntimeError, match="Apéndice 9"):
        anexo22.appendix_block(lines, headings, 9)


# ── parse_customs_offices (Apéndice 1) ──────────────────────────────────────


def test_parse_customs_offices_extrae_aduana_seccion_denominacion() -> None:
    lines = _lines("  01          0        Acapulco, Acapulco de Juárez, Guerrero.")

    filas = anexo22.parse_customs_offices(lines)

    assert filas == [anexo22.ParsedCustomsOffice("01", "0", "Acapulco, Acapulco de Juárez, Guerrero.")]


def test_parse_customs_offices_seccion_ausente_queda_none() -> None:
    """Dato real: aduana 17/Matamoros trae instalaciones sin sección propia."""
    lines = _lines("  17                   Puerto el Mezquital, Matamoros, Tamaulipas.")

    filas = anexo22.parse_customs_offices(lines)

    assert filas[0].aduana == "17"
    assert filas[0].seccion is None


def test_parse_customs_offices_junta_continuacion_envuelta() -> None:
    lines = _lines(
        "  24                   Aeropuerto Internacional      de     Nuevo   Laredo\n"
        '        "Quetzalcóatl", Nuevo Laredo, Tamaulipas.'
    )

    filas = anexo22.parse_customs_offices(lines)

    assert len(filas) == 1
    assert "Quetzalcóatl" in filas[0].name


def test_parse_customs_offices_ignora_pie_de_pagina() -> None:
    lines = _lines(
        "  01          0        Acapulco.\n"
        "  DIARIO OFICIAL\n"
        "  Jueves 15 de enero de 2026\n"
        "  02          0        Agua Prieta."
    )

    filas = anexo22.parse_customs_offices(lines)

    assert [f.aduana for f in filas] == ["01", "02"]


# ── parse_units_of_measure (Apéndice 7) ─────────────────────────────────────


def test_parse_units_of_measure() -> None:
    lines = _lines("                                      1                         Kilo\n" "Clave                 Descripción")

    filas = anexo22.parse_units_of_measure(lines)

    assert filas == [anexo22.ParsedUnitOfMeasure("1", "Kilo")]


# ── parse_pedimento_claves (Apéndice 2) ──────────────────────────────────────


def test_parse_pedimento_claves_extrae_solo_codigo() -> None:
    lines = _lines("A1    -   Importación o exportación definitiva.")

    filas = anexo22.parse_pedimento_claves(lines)

    assert filas == [anexo22.ParsedPedimentoClave("A1")]


def test_parse_pedimento_claves_no_confunde_t_mec_con_clave_t() -> None:
    """Regresión: "T-MEC" (sin espacios alrededor del guión) coincidía con el
    patrón `código - texto` antes de exigir espacio a ambos lados."""
    lines = _lines("                    T-MEC, 14 del Anexo III de la Decisión, 15 del Anexo I")

    filas = anexo22.parse_pedimento_claves(lines)

    assert filas == []


def test_parse_pedimento_claves_no_duplica_codigo_repetido() -> None:
    lines = _lines("A1    -   Importación o exportación definitiva.\n" "A1    -   otra vez por envoltura rara.")

    filas = anexo22.parse_pedimento_claves(lines)

    assert filas == [anexo22.ParsedPedimentoClave("A1")]


def test_parse_pedimento_claves_no_extrae_label() -> None:
    """El campo no existe en `ParsedPedimentoClave` — decisión deliberada, no
    un olvido (ver docstring del módulo)."""
    assert not hasattr(anexo22.ParsedPedimentoClave("A1"), "label")


# ── parse_non_tariff_regulations (Apéndice 9) ───────────────────────────────


_APENDICE_9_MUESTRA = (
    "Regulaciones y restricciones no arancelarias\n"
    "\n"
    "                                         Secretaría de Economía\n"
    "Clave                                               Descripción\n"
    " CA     Certificado de cupo adicional.\n"
    " C1     Permiso previo o permiso automático de importación definitiva, temporal.\n"
    "        Continúa en la siguiente línea con más detalle legal.\n"
    "\n"
    "                                            Secretaría de Energía\n"
    "Clave                                                 Descripción\n"
    " C1     Permiso previo de importación y exportación de hidrocarburos.\n"
)


def test_parse_non_tariff_regulations_agrupa_por_dependencia() -> None:
    filas = anexo22.parse_non_tariff_regulations(_lines(_APENDICE_9_MUESTRA))

    agencias = {f.code: f.issuing_agency for f in filas}
    assert agencias["CA"] == "Secretaría de Economía"


def test_parse_non_tariff_regulations_junta_continuacion_de_8_espacios() -> None:
    filas = anexo22.parse_non_tariff_regulations(_lines(_APENDICE_9_MUESTRA))

    c1_economia = next(f for f in filas if f.code == "C1" and f.issuing_agency == "Secretaría de Economía")
    assert "Continúa en la siguiente línea" in c1_economia.description


def test_parse_non_tariff_regulations_mismo_code_dos_dependencias() -> None:
    """Dato real: "C1" existe bajo Economía Y bajo Energía, con significados
    distintos — la llave natural es (code, issuing_agency), no code solo."""
    filas = anexo22.parse_non_tariff_regulations(_lines(_APENDICE_9_MUESTRA))

    c1_filas = [f for f in filas if f.code == "C1"]
    assert {f.issuing_agency for f in c1_filas} == {"Secretaría de Economía", "Secretaría de Energía"}
    assert len(c1_filas) == 2


def test_parse_non_tariff_regulations_no_arrastra_subtitulo_del_apendice() -> None:
    """El subtítulo del propio Apéndice 9 no debe colarse en el nombre de la
    primera dependencia real (regresión: se vio "Regulaciones y restricciones
    no arancelarias Secretaría de Economía" antes del filtro dedicado)."""
    filas = anexo22.parse_non_tariff_regulations(_lines(_APENDICE_9_MUESTRA))

    ca = next(f for f in filas if f.code == "CA")
    assert ca.issuing_agency == "Secretaría de Economía"
