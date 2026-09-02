"""Tests del health check (§14 P0 Persona 1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def test_liveness_responde_200_sin_infraestructura(client: TestClient) -> None:
    """Liveness no debe depender de Postgres, Redis, Neo4j ni MinIO."""
    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "aduanero-os"
    assert body["version"] == "0.1.0"
    assert body["timestamp"]


def test_readiness_reporta_servicios_sin_configurar(client: TestClient) -> None:
    """Sin credenciales, cada servicio es `not_configured`, no `down`.

    Distinguirlos importa: `not_configured` significa "aún no desplegado",
    `down` significa "desplegado y roto". Confundirlos haría que la API
    pareciese rota durante todo el Sprint 0.
    """
    resp = client.get("/health/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert set(body["services"]) == {"postgres", "redis", "neo4j", "minio"}
    for name, check in body["services"].items():
        assert check["status"] == "not_configured", f"{name}: {check}"


def test_readiness_devuelve_503_si_un_servicio_esta_caido(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un servicio configurado pero inalcanzable degrada la readiness a 503."""
    from apps.api.routers import health

    async def _postgres_caido(_settings: object) -> health.ServiceCheck:
        return health.ServiceCheck(status="down", detail="connection refused")

    monkeypatch.setattr(health, "_check_postgres", _postgres_caido)

    resp = client.get("/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["services"]["postgres"]["status"] == "down"


def test_openapi_se_genera(client: TestClient) -> None:
    """El esquema OpenAPI debe generarse: es el contrato que consumen P2 y P3."""
    resp = client.get("/openapi.json")

    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "ADUANERO OS API"
    assert "/health" in schema["paths"]
    assert "/health/ready" in schema["paths"]
