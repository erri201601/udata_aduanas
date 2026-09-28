"""Tests de `ingestion.dof.rgce.fracciones_de` contra un fragmento real de la
regla 1.1.6 de las RGCE 2026 (46 094 caracteres en la regla más larga, 7.3.3
-- ninguna de las tres cabe en el embedder de OpenAI sin partirse)."""

from __future__ import annotations

import pytest
from ingestion.dof.rgce import fracciones_de

from tests.fixtures.rgce_2026_regla_larga_fragmento import REGLA_1_1_6_FRAGMENTO

pytestmark = pytest.mark.unit


def test_encuentra_las_tres_fracciones_reales_en_orden() -> None:
    fracciones = fracciones_de(REGLA_1_1_6_FRAGMENTO)

    assert [rom for rom, _ in fracciones] == ["I", "II", "III"]


def test_cada_fraccion_es_mucho_mas_corta_que_la_regla_completa() -> None:
    fracciones = fracciones_de(REGLA_1_1_6_FRAGMENTO)

    assert all(len(texto) < len(REGLA_1_1_6_FRAGMENTO) for _, texto in fracciones)
    assert max(len(texto) for _, texto in fracciones) < 3000


def test_la_fraccion_i_no_se_corta_en_los_incisos_a_y_b_internos() -> None:
    """Los incisos "a)"/"b)" dentro de la fracción I son parte de SU texto,
    no encabezados de fracción propios -- `fracciones_de` sólo reconoce
    números romanos, nunca letras."""
    primera = fracciones_de(REGLA_1_1_6_FRAGMENTO)[0][1]

    assert "a) Conforme a las cantidades" in primera
    assert "b) De esta manera" in primera
    assert primera.endswith("aplicado fue de 1.4306.")


def test_no_confunde_citas_de_fracciones_de_ley_con_encabezados() -> None:
    """ "185, fracciones I a VI, VIII a XII y XIV" cita fracciones de OTRO
    artículo dentro de la prosa -- no son encabezados de fracción de esta
    regla, y no deben aparecer como tales en la lista devuelta."""
    fracciones = fracciones_de(REGLA_1_1_6_FRAGMENTO)

    assert [rom for rom, _ in fracciones] == ["I", "II", "III"]
    assert "185, fracciones I a VI" in fracciones[0][1]


def test_sin_fracciones_devuelve_lista_vacia() -> None:
    assert fracciones_de("Una regla sin ninguna fracción romana dentro.") == []


def test_secuencia_no_consecutiva_no_se_particiona() -> None:
    """Un romano que calza el patrón (tras ". ", seguido de mayúscula) pero
    no continúa la secuencia -- aquí salta de I a IV -- no se arriesga como
    partición: la regla se deja sin trocear en vez de partirla mal."""
    texto = "Primero esto. I. Una fracción real. Referencia aparte. IV. Esto no es la II."

    assert fracciones_de(texto) == []


def test_secuencia_con_salto_no_se_particiona() -> None:
    texto = "Inicio: I. Primera fracción. III. Salta la segunda, no es válido."

    assert fracciones_de(texto) == []
