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
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

import structlog

P = ParamSpec("P")
R = TypeVar("R")

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


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


@dataclass
class Corrida:
    """Lo que una ejecución va sabiendo de sí misma, para el registro final."""

    run_id: str
    module: str
    log: structlog.stdlib.BoundLogger
    records: int | None = None
    errors: int = 0
    datos: dict[str, Any] = field(default_factory=dict)
    """`model`, `prompt_version` y lo que el módulo quiera dejar en el cierre."""


_CORRIDA: ContextVar[Corrida | None] = ContextVar("corrida", default=None)


def registrar(*, records: int | None = None, errors: int = 0, **datos: Any) -> None:
    """Anota en la ejecución en curso lo que debe salir en su `run.finished`.

    Sin ejecución en curso no hace nada: un motor llamado desde un test o desde
    otro motor no tiene por qué saber si alguien lo está midiendo.
    """
    corrida = _CORRIDA.get()
    if corrida is None:
        return
    if records is not None:
        corrida.records = (corrida.records or 0) + records
    corrida.errors += errors
    corrida.datos.update(datos)


@contextmanager
def run_context(module: str, **extra: Any) -> Iterator[Corrida]:
    """Envuelve la ejecución de un pipeline o un motor y emite el registro del §37.

    Uso:
        with run_context("ingestion.dof.watcher") as corrida:
            ...
            registrar(records=creados)

    - `run.started` al entrar; `run.finished` (status OK o FAILED) al salir,
      con `run_id`, `module`, `started_at`, `finished_at`, `duration_ms`,
      `records`, `errors` y lo anotado con `registrar` (modelo, prompt…).
    - El `run_id` se fija en el contexto de structlog: TODOS los logs de la
      ejecución lo llevan, también los de `core/`, sin que `core` lo sepa.
    - Un `SystemExit` con código distinto de 0 cuenta como FAILED: es como
      terminan los CLI cuando algo no se puede hacer.

    Hasta el 20-oct esto existía y nadie lo llamaba (§37 sin cumplir).
    """
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    tokens = structlog.contextvars.bind_contextvars(run_id=run_id, module=module)
    log = get_logger(module).bind(**extra)
    corrida = Corrida(run_id=run_id, module=module, log=log)
    marca = _CORRIDA.set(corrida)
    log.info("run.started", started_at=started.isoformat())
    estado, error = "OK", None
    try:
        yield corrida
    except SystemExit as exc:
        if exc.code not in (None, 0):
            estado, error = "FAILED", f"SystemExit({exc.code})"
        raise
    except BaseException as exc:
        estado, error = "FAILED", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        finished = datetime.now(UTC)
        campos: dict[str, Any] = {
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_ms": int((finished - started).total_seconds() * 1000),
            "status": estado,
            "records": corrida.records,
            "errors": corrida.errors + (1 if error else 0),
            **corrida.datos,
        }
        if error:
            log.error("run.finished", error=error, **campos)
        else:
            log.info("run.finished", **campos)
        _CORRIDA.reset(marca)
        structlog.contextvars.reset_contextvars(**tokens)


def con_corrida(module: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorador de `main()` de un CLI: su ejecución entera es una corrida."""

    def decorador(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def envuelta(*args: P.args, **kwargs: P.kwargs) -> R:
            with run_context(module):
                return fn(*args, **kwargs)

        return envuelta

    return decorador
