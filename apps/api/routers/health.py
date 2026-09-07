"""Health checks (§14 P0 Persona 1).

Dos niveles, deliberadamente distintos:

* ``/health``       liveness  — ¿el proceso responde? Nunca toca dependencias.
* ``/health/ready`` readiness — ¿puede el sistema hacer trabajo real?
                    Comprueba Postgres, Redis, Neo4j y MinIO por separado.

La readiness NO lanza excepción cuando un servicio está caído: reporta su
estado y devuelve 503. Esto permite arrancar la API sin infraestructura,
que es exactamente la situación mientras Docker no esté instalado.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from apps.api.config import Settings, get_settings

router = APIRouter(tags=["health"])

ServiceStatus = Literal["up", "down", "not_configured"]

# Un servicio caído debe reportarse rápido, no colgar el endpoint.
PROBE_TIMEOUT_SECONDS = 3.0


class ServiceCheck(BaseModel):
    """Resultado de sondear una dependencia."""

    status: ServiceStatus
    latency_ms: int | None = None
    detail: str | None = None


class LivenessResponse(BaseModel):
    """Respuesta de liveness."""

    status: Literal["ok"] = "ok"
    app: str
    env: str
    version: str
    timestamp: str


class ReadinessResponse(BaseModel):
    """Respuesta de readiness, con el detalle por dependencia."""

    status: Literal["ready", "degraded"]
    timestamp: str
    services: dict[str, ServiceCheck] = Field(default_factory=dict)


async def _timed(probe: Any) -> ServiceCheck:
    """Ejecuta un sondeo en hilo aparte, con timeout, y lo convierte a ServiceCheck."""
    started = datetime.now(UTC)
    try:
        await asyncio.wait_for(asyncio.to_thread(probe), timeout=PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        return ServiceCheck(status="down", detail=f"timeout > {PROBE_TIMEOUT_SECONDS}s")
    except Exception as exc:  # cualquier fallo es "down", con su causa
        return ServiceCheck(status="down", detail=f"{type(exc).__name__}: {exc}"[:200])
    elapsed = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return ServiceCheck(status="up", latency_ms=elapsed)


async def _check_postgres(settings: Settings) -> ServiceCheck:
    """Sondea PostgreSQL y confirma que pgvector esté instalada."""
    if not settings.postgres_password.get_secret_value() and not settings.database_url:
        return ServiceCheck(status="not_configured", detail="sin POSTGRES_PASSWORD")

    def probe() -> None:
        from sqlalchemy import text

        from apps.api.db import get_engine

        # Engine compartido, no uno por sondeo: cuatro servicios se comprueban
        # en paralelo y crear un engine por llamada abría —y tiraba— una
        # conexión nueva cada vez contra una base que vive tras Tailscale.
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            found = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            if not found:
                raise RuntimeError("extensión pgvector ausente")

    return await _timed(probe)


async def _check_redis(settings: Settings) -> ServiceCheck:
    """Sondea Redis con PING."""
    if not settings.redis_password.get_secret_value() and not settings.redis_url:
        return ServiceCheck(status="not_configured", detail="sin REDIS_PASSWORD")

    def probe() -> None:
        import redis

        client = redis.from_url(settings.effective_redis_url, socket_timeout=PROBE_TIMEOUT_SECONDS)
        try:
            client.ping()
        finally:
            client.close()

    return await _timed(probe)


async def _check_neo4j(settings: Settings) -> ServiceCheck:
    """Sondea Neo4j con verify_connectivity."""
    if not settings.neo4j_password.get_secret_value():
        return ServiceCheck(status="not_configured", detail="sin NEO4J_PASSWORD")

    def probe() -> None:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
        )
        try:
            driver.verify_connectivity()
        finally:
            driver.close()

    return await _timed(probe)


async def _check_minio(settings: Settings) -> ServiceCheck:
    """Sondea MinIO comprobando que exista el bucket RAW."""
    if not settings.minio_root_password.get_secret_value():
        return ServiceCheck(status="not_configured", detail="sin MINIO_ROOT_PASSWORD")

    def probe() -> None:
        from minio import Minio

        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password.get_secret_value(),
            secure=settings.minio_secure,
        )
        if not client.bucket_exists(settings.minio_bucket_raw):
            raise RuntimeError(f"bucket '{settings.minio_bucket_raw}' inexistente")

    return await _timed(probe)


@router.get("/health", response_model=LivenessResponse, summary="Liveness")
async def health() -> LivenessResponse:
    """Liveness. Responde 200 mientras el proceso viva; no toca dependencias."""
    settings = get_settings()
    return LivenessResponse(
        app=settings.app_name,
        env=settings.app_env,
        version="0.1.0",
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness")
async def readiness(response: Response) -> ReadinessResponse:
    """Readiness. 200 si todo lo configurado responde; 503 si algo está caído.

    Un servicio `not_configured` no degrada el resultado: significa que aún no
    forma parte del despliegue, no que esté roto.
    """
    settings = get_settings()

    names = ("postgres", "redis", "neo4j", "minio")
    results = await asyncio.gather(
        _check_postgres(settings),
        _check_redis(settings),
        _check_neo4j(settings),
        _check_minio(settings),
    )
    services = dict(zip(names, results, strict=True))

    degraded = any(check.status == "down" for check in services.values())
    if degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="degraded" if degraded else "ready",
        timestamp=datetime.now(UTC).isoformat(),
        services=services,
    )
