"""Tests de `ingestion.snice.cli`: validación de argumentos, sin red ni MinIO."""

from __future__ import annotations

import pytest
from ingestion.snice.cli import main

pytestmark = pytest.mark.unit


def test_chapters_es_obligatorio_sin_raw_only() -> None:
    with pytest.raises(SystemExit, match="--chapters, --notes o --headings es obligatorio"):
        main(["--target", "local"])


def test_notes_solo_no_exige_chapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--notes` es una carga independiente de `--chapters`: las notas son del
    documento completo, no de los capítulos que además se estén cargando.

    `--target shared` sin `ADUANERO_SHARED_URL` fallará más adelante buscando
    la URL de la base — deterministamente, sin red — lo que confirma que
    `--notes` solo ya pasó la validación de argumentos obligatorios.
    """
    monkeypatch.delenv("ADUANERO_SHARED_URL", raising=False)

    with pytest.raises(SystemExit, match="ADUANERO_SHARED_URL"):
        main(["--target", "shared", "--notes"])


def test_chunks_sin_notes_falla() -> None:
    """`--chunks` sólo tiene sentido junto a `--notes`: falla ruidoso en vez de
    ignorarlo en silencio (regla 7 CLAUDE.md)."""
    with pytest.raises(SystemExit, match="--chunks sólo tiene efecto junto con --notes"):
        main(["--target", "local", "--chapters", "84", "--chunks"])


def test_raw_only_no_exige_chapters_ni_la_url_de_la_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--raw-only` no toca la base: no debe pedir `ADUANERO_SHARED_URL`. Falla más
    adelante, al buscar las credenciales de MinIO compartido (no configuradas aquí),
    lo que confirma que sí pasó de largo la validación de `--chapters` y de la base."""
    monkeypatch.delenv("ADUANERO_SHARED_URL", raising=False)
    monkeypatch.delenv("ADUANERO_SHARED_MINIO_URL", raising=False)

    with pytest.raises(RuntimeError, match="ADUANERO_SHARED_MINIO_URL"):
        main(["--target", "shared", "--raw-only"])
