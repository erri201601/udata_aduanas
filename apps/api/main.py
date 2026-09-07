"""Punto de entrada de la API de ADUANERO OS.

Ejecutar en desarrollo:
    uvicorn apps.api.main:app --reload --port 8080

El puerto es 8080, no 8000: el 8000 está ocupado por otro proyecto en el
dev server de Persona 1.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.config import get_settings
from apps.api.db import dispose_engine
from apps.api.logging import configure_logging, get_logger
from apps.api.routers import classifications, health, products

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DESCRIPTION = """
Capa de inteligencia para comercio exterior mexicano — UDATA.

**Marcado de datos (§33 maestro).** Toda respuesta que exponga datos debe
declarar su `data_origin`: `OFFICIAL`, `PUBLIC`, `LICENSED`, `SYNTHETIC` o
`HUMAN_VALIDATED`. Los datos operativos del MVP son **SYNTHETIC DEMO DATA**;
las fuentes jurídicas son reales.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Arranque y apagado. No abre conexiones: eso lo decide cada router."""
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    log = get_logger("apps.api")
    log.info(
        "api.startup",
        app=settings.app_name,
        env=settings.app_env,
        port=settings.api_port,
    )
    yield
    # Devuelve las conexiones al servidor. Sin esto, cada reinicio en desarrollo
    # deja un pool colgado en el PostgreSQL compartido del dev server.
    dispose_engine()
    log.info("api.shutdown", app=settings.app_name)


def create_app() -> FastAPI:
    """Construye la aplicación FastAPI."""
    settings = get_settings()

    app = FastAPI(
        title="ADUANERO OS API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        # La documentación interactiva sólo fuera de producción.
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
    )

    # En local, el frontend Vite corre en 5173. En producción se restringe.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(products.router)
    app.include_router(classifications.router)
    return app


app = create_app()
