"""Tests de `ingestion.se.cli`: validación de argumentos, sin red ni MinIO."""

from __future__ import annotations

import pytest
from ingestion.se.cli import main

pytestmark = pytest.mark.unit


def test_cable_acero_china_es_obligatorio_sin_raw_only() -> None:
    with pytest.raises(SystemExit, match="--cable-acero-china es obligatorio"):
        main(["--target", "local"])


def test_raw_only_no_exige_ningun_flag_ni_la_url_de_la_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADUANERO_SHARED_URL", raising=False)
    monkeypatch.delenv("ADUANERO_SHARED_MINIO_URL", raising=False)

    with pytest.raises(RuntimeError, match="ADUANERO_SHARED_MINIO_URL"):
        main(["--target", "shared", "--raw-only"])
