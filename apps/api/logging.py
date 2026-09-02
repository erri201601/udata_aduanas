"""Logging estructurado (§37 maestro).

Cada pipeline y motor debe poder emitir: run_id, module, started_at,
finished_at, status, duration_ms, records, errors, model, prompt_version.
Aquí se define el transporte; cada módulo aporta sus campos.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterator


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configura structlog y el logging estándar de la librería."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Logger nombrado, ya configurado."""
    return structlog.stdlib.get_logger(name)


@contextmanager
def run_context(module: str, **extra: Any) -> Iterator[structlog.stdlib.BoundLogger]:
    """Envuelve la ejecución de un pipeline y emite el registro de §37.

    Uso:
        with run_context("ingestion.dof", source="DOF") as log:
            log.info("descargando", url=url)

    Emite `run.started` al entrar y `run.finished` / `run.failed` al salir,
    siempre con `run_id` y `duration_ms`.
    """
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    log = get_logger(module).bind(run_id=run_id, module=module, **extra)
    log.info("run.started", started_at=started.isoformat())
    try:
        yield log
    except Exception as exc:
        finished = datetime.now(UTC)
        log.error(
            "run.failed",
            finished_at=finished.isoformat(),
            duration_ms=int((finished - started).total_seconds() * 1000),
            status="FAILED",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    else:
        finished = datetime.now(UTC)
        log.info(
            "run.finished",
            finished_at=finished.isoformat(),
            duration_ms=int((finished - started).total_seconds() * 1000),
            status="OK",
        )
