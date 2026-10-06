"""Tests de `ingestion.dof.anexo22.parse_identifiers_con_texto` (y su
función por página, `_identificadores_de_pagina`) -- `label` +
`supuestos_de_aplicacion` del Apéndice 8, por coordenadas.

`unit`, sin red ni PDF real: usa el fragmento verbatim de
`tests/fixtures/anexo22_apendice8_pagina142_bbox.py` para el caso de una
sola página, y páginas sintéticas para el estado que cruza entre páginas.
"""

from __future__ import annotations

import subprocess

import pytest
from ingestion.dof import anexo22
from ingestion.dof.anexo22 import (
    _CODIGO_SOLO_RE,
    _IDENTIFICADOR_APENDICE_RE,
    ParsedIdentifier,
    _identificadores_de_pagina,
    paginas_de_apendice,
    parse_identifiers_con_texto,
)
from ingestion.snice.tariff_headings import _Palabra, _palabras_de

from tests.fixtures.anexo22_apendice8_pagina142_bbox import APENDICE_8_PAGINA_142

pytestmark = pytest.mark.unit


def _resultado_pagina_142() -> list[ParsedIdentifier]:
    return _identificadores_de_pagina(_palabras_de(APENDICE_8_PAGINA_142))


def test_las_cinco_entradas_completas_de_la_pagina() -> None:
    res = _resultado_pagina_142()
    assert [p.code for p in res] == ["AC", "AE", "AF", "AG", "AI"]


def test_label_y_supuestos_no_llevan_el_codigo_pegado() -> None:
    """Regresión real: "AC-" se quedaba pegado al frente del label antes de
    excluir el encabezado de columnas por posición Y."""
    res = {p.code: p for p in _resultado_pagina_142()}
    assert res["AC"].label == "Almacén general de depósito certificado."
    assert res["AC"].supuestos_de_aplicacion == (
        "Identificar a un almacén general de depósito certificado."
    )


def test_ninguna_entrada_trae_texto_de_otra_columna_mezclado() -> None:
    """Regresión real: "Número" (Complemento 1, x=359.9) se colaba en
    Supuestos de Aplicación (AC) porque el corte de columna (x<360) le
    daba 0.1pt de margen. Ninguna de las 5 debe contener palabras de
    Complemento (reconocibles porque allí "Número"/"Declarar la clave que
    corresponda" son frases de instrucción de captura, no de supuesto)."""
    res = _resultado_pagina_142()
    for p in res:
        assert "Número" not in (p.supuestos_de_aplicacion or "")


def test_sin_entradas_el_resultado_es_vacio() -> None:
    assert _identificadores_de_pagina([]) == []


def test_un_guion_largo_tambien_cuenta_como_codigo() -> None:
    """Regresión real: "CR–"/"PB–" (guión largo U+2013 pegado al código)
    no coincidían con el regex original, que sólo aceptaba "-" (guión
    normal) opcional."""
    assert _CODIGO_SOLO_RE.match("CR–")
    assert _CODIGO_SOLO_RE.match("AC-")
    assert _CODIGO_SOLO_RE.match("AF")


def test_el_regex_de_layout_tambien_acepta_guion_largo() -> None:
    """El mismo hallazgo, para `parse_identifiers` (el parser de texto
    plano, no bbox): CR, EO, PB y PO usan "–" en el documento real y antes
    de este fix no se cargaban -- 4 claves reales perdidas en silencio."""
    m = _IDENTIFICADOR_APENDICE_RE.match("EO – Emisor del certificado")
    assert m is not None
    assert m.group(1) == "EO"


# ── Estado que cruza entre páginas (sintético, sin PDF real) ────────────────


def test_una_entrada_puede_leerse_con_palabras_sinteticas() -> None:
    """No depende del fixture real: construye una página mínima a mano para
    verificar que una sola ancla con su label y supuesto en columnas
    separadas se lee completa, sin red ni PDF."""
    palabras = [
        _Palabra(72.0, 100.0, "ZZ-"),
        _Palabra(90.0, 100.0, "Etiqueta"),
        _Palabra(130.0, 100.0, "corta."),
        _Palabra(190.0, 100.0, "G"),
        _Palabra(220.0, 100.0, "Supuesto"),
        _Palabra(260.0, 100.0, "de"),
        _Palabra(280.0, 100.0, "prueba."),
    ]
    (res,) = _identificadores_de_pagina(palabras)
    assert res.code == "ZZ"
    assert res.level == "G"
    assert res.label == "Etiqueta corta."
    assert res.supuestos_de_aplicacion == "Supuesto de prueba."


def test_el_guion_largo_suelto_no_se_queda_pegado_al_label() -> None:
    """Regresión real: EO y PO traen el guión largo como palabra bbox
    SEPARADA del código ("EO", "–" como dos tokens, no "EO-" pegado como
    AC) -- sin despegarlo, el label real salía "– Emisor del certificado
    de origen." con el guión colgando al frente."""
    palabras = [
        _Palabra(72.0, 100.0, "EO"),
        _Palabra(85.0, 100.0, "–"),
        _Palabra(95.0, 100.0, "Emisor"),
        _Palabra(130.0, 100.0, "del"),
        _Palabra(150.0, 100.0, "certificado."),
        _Palabra(190.0, 100.0, "P"),
        _Palabra(220.0, 100.0, "Supuesto."),
    ]
    (res,) = _identificadores_de_pagina(palabras)
    assert res.code == "EO"
    assert res.label == "Emisor del certificado."


def test_un_codigo_con_nivel_g_y_p_no_pierde_ninguno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresión real: `parse_identifiers_con_texto` deduplicaba por `code`
    solo -- 6 claves reales repiten código con nivel G Y P, cada una con su
    propia etiqueta y supuesto (caso real: "CF", página 147, "Registro..."
    G vs "Preferencia..." P). Con `code` solo como clave de dedup, la
    segunda se perdía en silencio."""
    xml = (
        '<word xMin="72.0" yMin="100.0" xMax="90.0" yMax="110.0">CF-</word>'
        '<word xMin="93.6" yMin="100.0" xMax="140.0" yMax="110.0">Registro.</word>'
        '<word xMin="188.8" yMin="100.0" xMax="195.0" yMax="110.0">G</word>'
        '<word xMin="220.0" yMin="100.0" xMax="260.0" yMax="110.0">Supuesto</word>'
        '<word xMin="263.0" yMin="100.0" xMax="266.0" yMax="110.0">G.</word>'
        '<word xMin="72.0" yMin="130.0" xMax="90.0" yMax="140.0">CF-</word>'
        '<word xMin="93.6" yMin="130.0" xMax="150.0" yMax="140.0">Preferencia.</word>'
        '<word xMin="188.8" yMin="130.0" xMax="195.0" yMax="140.0">P</word>'
        '<word xMin="220.0" yMin="130.0" xMax="260.0" yMax="140.0">Supuesto</word>'
        '<word xMin="263.0" yMin="130.0" xMax="266.0" yMax="140.0">P.</word>'
    )
    monkeypatch.setattr(anexo22, "extract_bbox_pages", lambda *a, **kw: iter([(1, xml)]))

    res = parse_identifiers_con_texto("/no/existe.pdf", first_page=1, last_page=1)

    cf = {p.level: p for p in res if p.code == "CF"}
    assert set(cf) == {"G", "P"}
    assert cf["G"].label == "Registro."
    assert cf["P"].label == "Preferencia."


def test_paginas_de_apendice_localiza_por_encabezado_no_por_numero_fijo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 páginas sintéticas: Apéndice 7 en la 1, Apéndice 8 ocupa toda la 2,
    Apéndice 9 abre la 3. Verifica que el rango calculado son páginas
    físicas reales (1-based), no índices de línea."""
    pagina_1 = "                                                 Apéndice 7\ntexto 7\n"
    pagina_2 = "                                                 Apéndice 8\ntexto 8a\ntexto 8b\n"
    pagina_3 = "                                                 Apéndice 9\ntexto 9\n"
    stdout = "\x0c".join([pagina_1, pagina_2, pagina_3])

    def _run_falso(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=(), returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(anexo22.subprocess, "run", _run_falso)

    first_page, last_page = paginas_de_apendice("/no/existe.pdf", 8)

    assert first_page == 2
    assert last_page == 2


def test_paginas_de_apendice_excluye_entera_la_pagina_del_siguiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Límite real conocido, verificado contra el documento (página 198: el
    Apéndice 9 no trae ninguna fila del Apéndice 8 antes de su encabezado,
    sólo pie de página repetido) -- si algún día SÍ hubiera texto real del
    Apéndice 8 colado antes del encabezado siguiente en la misma página
    física, esta función lo pierde: `extract_bbox_pages` sólo pide páginas
    enteras, no puede cortar a media página como sí hace `appendix_block`
    con líneas."""
    pagina_1 = "                                                 Apéndice 8\ntexto 8a\n"
    pagina_2 = "texto 8b (se pierde)\n                                       Apéndice 9\ntexto 9\n"
    stdout = "\x0c".join([pagina_1, pagina_2])

    def _run_falso(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=(), returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(anexo22.subprocess, "run", _run_falso)

    first_page, last_page = paginas_de_apendice("/no/existe.pdf", 8)

    assert (first_page, last_page) == (1, 1)


def test_el_encabezado_de_columnas_no_se_mezcla_con_la_primera_entrada() -> None:
    """Sintético: "Nivel" (encabezado) aparece antes del ancla real -- su
    texto en la columna de Supuestos no debe colarse en la primera
    entrada."""
    palabras = [
        _Palabra(114.0, 50.0, "Clave"),
        _Palabra(190.0, 50.0, "Nivel"),
        _Palabra(220.0, 50.0, "Supuestos"),
        _Palabra(72.0, 100.0, "ZZ-"),
        _Palabra(90.0, 100.0, "Etiqueta."),
        _Palabra(190.0, 100.0, "G"),
        _Palabra(220.0, 100.0, "Texto"),
        _Palabra(250.0, 100.0, "real."),
    ]
    (res,) = _identificadores_de_pagina(palabras)
    assert res.supuestos_de_aplicacion == "Texto real."
    assert "Supuestos" not in res.supuestos_de_aplicacion
