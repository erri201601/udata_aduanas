"""Tests del extractor de partidas/subpartidas de la LIGIE (ADR 0002).

`unit` — sin red ni PDF real: usa fragmentos bbox reales
(`tests/fixtures/ligie_bbox_fragmentos.py`, recortes literales de
`pdftotext -bbox-layout` sobre el PDF real ya verificado en MinIO).

Regresiones reales encontradas al validar contra el documento, no contra
datos inventados:

1. El punto medio entre código vecino y código vecino le roba su última
   línea a la fila anterior cuando ésta es larga y la siguiente corta
   (84.01, 4 líneas, seguida de 8401.10, 1 línea). Se resolvió con una
   partición global por programación dinámica.
2. El ruido institucional que se repite en cada página ("Dirección General
   de Facilitación Comercial y de Comercio Exterior") no se puede filtrar
   por palabra: trae conectores comunes ("de", "y") indistinguibles de
   texto real. Se filtra por posición Y contra el encabezado/pie de esa
   página.
3. Rechazar una fila puntual por no ajustar dentro de la tolerancia no
   puede desalinear el puntero de línea para las filas que siguen: la
   partición es de toda la página, no fila por fila.
"""

from __future__ import annotations

import pytest
from ingestion.snice.tariff_headings import _headings_de_pagina, _palabras_de

from tests.fixtures.ligie_bbox_fragmentos import (
    PAGINA_33_CAPITULO_3,
    PAGINA_604_CAPITULO_61,
    PAGINA_889_CAPITULO_84,
)

pytestmark = pytest.mark.unit


def test_extrae_partida_de_cuatro_lineas_completa_sin_perder_la_ultima() -> None:
    """Regresión: 84.01 tiene 4 líneas reales de descripción. El punto medio
    con la subpartida vecina (1 línea) le robaba la última."""
    palabras = _palabras_de(PAGINA_889_CAPITULO_84)
    encontrados = {c: (n, t) for c, n, t in _headings_de_pagina(palabras)}

    assert "8401" in encontrados
    nivel, texto = encontrados["8401"]
    assert nivel == 4
    assert texto == (
        "Reactores nucleares; elementos combustibles (cartuchos) sin irradiar para reactores "
        "nucleares; máquinas y aparatos para la separación isotópica."
    )


def test_subpartida_de_una_sola_linea_no_hereda_texto_de_la_partida() -> None:
    palabras = _palabras_de(PAGINA_889_CAPITULO_84)
    encontrados = {c: (n, t) for c, n, t in _headings_de_pagina(palabras)}

    assert encontrados["840110"] == (6, "Reactores nucleares.")


def test_ninguna_partida_o_subpartida_trae_ruido_institucional() -> None:
    """Regresión: "Dirección General de Facilitación Comercial y de Comercio
    Exterior" se filtraba mal por palabra -- se cuela por sus conectores
    comunes. Verificado en las tres páginas reales, no sólo una."""
    fragmentos_ruido = ("Dirección General", "Facilitación", "Comercio Exterior", "Pachuca")
    for pagina in (PAGINA_889_CAPITULO_84, PAGINA_604_CAPITULO_61, PAGINA_33_CAPITULO_3):
        palabras = _palabras_de(pagina)
        for _, _, texto in _headings_de_pagina(palabras):
            for ruido in fragmentos_ruido:
                assert ruido not in texto, f"{ruido!r} se coló en {texto!r}"


def test_ninguna_fila_repite_texto_de_su_vecina() -> None:
    """Regresión real: antes de la partición global, filas consecutivas de
    calderas (84.02) devolvían texto que se solapaba entre sí (el mismo
    fragmento de "vapor superior a 45 t por hora" apareciendo en dos filas
    seguidas). Cada texto debe ser distinto de sus vecinas inmediatas."""
    palabras = _palabras_de(PAGINA_889_CAPITULO_84)
    encontrados = _headings_de_pagina(palabras)
    textos = [t for _, _, t in encontrados]
    for i in range(len(textos) - 1):
        assert textos[i] != textos[i + 1]


def test_capitulo_61_no_mezcla_prendas_con_encabezado_de_pagina() -> None:
    palabras = _palabras_de(PAGINA_604_CAPITULO_61)
    encontrados = {c: (n, t) for c, n, t in _headings_de_pagina(palabras)}

    # Lo que sí se recuperó, real y verificado a mano contra el PDF.
    assert encontrados.get("610210") == (6, "De lana o pelo fino.")
    assert encontrados.get("610220") == (6, "De algodón.")
    for _, (_, texto) in encontrados.items():
        assert "Facilitación" not in texto
        assert "Pachuca" not in texto


def test_capitulo_3_pescado_subpartidas_reales() -> None:
    palabras = _palabras_de(PAGINA_33_CAPITULO_3)
    encontrados = {c: (n, t) for c, n, t in _headings_de_pagina(palabras)}

    assert encontrados.get("030274") == (6, "Anguilas (Anguilla spp.).")
    assert encontrados.get("030284") == (6, "Róbalos (Dicentrarchus spp.).")


def test_nunca_devuelve_una_fraccion_de_ocho_digitos() -> None:
    """Las fracciones (nivel 8) sólo sirven de ancla -- ya se cargan del
    XLSX de SNICE, cargarlas aquí también duplicaría la fuente."""
    for pagina in (PAGINA_889_CAPITULO_84, PAGINA_604_CAPITULO_61, PAGINA_33_CAPITULO_3):
        palabras = _palabras_de(pagina)
        for code, nivel, _ in _headings_de_pagina(palabras):
            assert nivel in (4, 6), f"{code} salió con nivel {nivel}"
