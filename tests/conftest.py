"""Fixtures compartidas.

Los tests unitarios no deben tocar la infraestructura: se fuerzan credenciales
vacías para que los health checks reporten `not_configured` en vez de intentar
conectarse a servicios que aún no existen.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests del .env real del desarrollador."""
    for var in (
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "NEO4J_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "DATABASE_URL",
        "REDIS_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LOG_FORMAT", "console")
    # Vacío = no leer ningún .env. Sin esto los tests heredarían las
    # credenciales reales del desarrollador e intentarían conectarse a
    # servicios que no existen.
    monkeypatch.setenv("ADUANERO_ENV_FILE", "")

    from apps.api.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Cliente HTTP contra la app, sin infraestructura externa."""
    from apps.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def repo_root() -> Path:
    """Raíz del repositorio."""
    return Path(__file__).resolve().parent.parent
