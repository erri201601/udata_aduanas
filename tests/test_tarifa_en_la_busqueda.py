"""Los textos de la tarifa como fragmentos del RAG (§27)."""

from __future__ import annotations

import pytest
from ingestion.snice import tarifa_chunks
from ingestion.snice.tarifa_chunks import fragmentos_de_la_tarifa

pytestmark = pytest.mark.unit

PARTIDAS = [("7312", "Cables, trenzas, eslingas…, de hierro o acero.")]
SUBPARTIDAS = [("731210", "Cables."), ("731290", "Los demás.")]
FRACCIONES = [
    ("73121005", "De acero sin recubrimiento."),
    ("73121099", "Los demás."),
    ("73129099", "Los demás."),
]


def test_un_fragmento_por_partida_con_su_jerarquia() -> None:
    [f] = fragmentos_de_la_tarifa(PARTIDAS, SUBPARTIDAS, FRACCIONES)
    assert f.article == "Partida 73.12"
    lineas = f.text.splitlines()
    assert lineas[0].startswith("73.12 Cables")
    assert "  7312.10 Cables." in lineas
    assert "    7312.10.05 De acero sin recubrimiento." in lineas
    # «Los demás.» de la 7312.10 queda bajo su subpartida, no suelto.
    assert lineas.index("    7312.10.99 Los demás.") < lineas.index("  7312.90 Los demás.")


def test_una_partida_larga_se_parte_por_subpartida_con_su_encabezado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tarifa_chunks, "MAXIMO", 60)
    fragmentos = fragmentos_de_la_tarifa(PARTIDAS, SUBPARTIDAS, FRACCIONES)
    assert [f.article for f in fragmentos] == [
        "Partida 73.12 (7312.10)",
        "Partida 73.12 (7312.90)",
    ]
    assert all(f.text.startswith("73.12 Cables") for f in fragmentos)


def test_fracciones_sin_subpartida_propia_no_se_pierden() -> None:
    [f] = fragmentos_de_la_tarifa(
        [("9802", "Mercancías para programas.")], [], [("98020001", "Para la Eléctrica.")]
    )
    assert "9802.00.01 Para la Eléctrica." in f.text
