"""Tests de `ingestion.snice.cli`: validación de argumentos, sin red ni MinIO."""

from __future__ import annotations

import pytest
from ingestion.snice.cli import main

pytestmark = pytest.mark.unit


def test_chapters_es_obligatorio_sin_raw_only() -> None:
    with pytest.raises(SystemExit, match="--chapters es obligatorio"):
        main(["--target", "local"])


def test_raw_only_no_exige_chapters_ni_la_url_de_la_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--raw-only` no toca la base: no debe pedir `ADUANERO_SHARED_URL`. Falla más
    adelante, al buscar las credenciales de MinIO compartido (no configuradas aquí),
    lo que confirma que sí pasó de largo la validación de `--chapters` y de la base."""
    monkeypatch.delenv("ADUANERO_SHARED_URL", raising=False)
    monkeypatch.delenv("ADUANERO_SHARED_MINIO_URL", raising=False)

    with pytest.raises(RuntimeError, match="ADUANERO_SHARED_MINIO_URL"):
        main(["--target", "shared", "--raw-only"])
