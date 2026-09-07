"""Tests de la capa de sesión.

Ninguno toca PostgreSQL. Construir un engine o una sesión no abre conexión
—SQLAlchemy conecta al ejecutar— y eso es justo lo que se comprueba: que
importar la API y pedir una sesión no exija infraestructura levantada.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from apps.api import db
from sqlalchemy import Engine
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _engine_limpio() -> Iterator[None]:
    """Cada test parte y termina sin engine: las cachés son de proceso."""
    db.get_sessionmaker.cache_clear()
    db.get_engine.cache_clear()
    yield
    db.get_sessionmaker.cache_clear()
    db.get_engine.cache_clear()


def test_importar_el_modulo_no_crea_el_engine() -> None:
    """La API tiene que arrancar sin PostgreSQL."""
    assert db.get_engine.cache_info().currsize == 0


def test_el_engine_es_sincrono() -> None:
    """No hay async en el repo: meterlo aquí crearía dos mundos."""
    engine = db.get_engine()

    assert isinstance(engine, Engine)
    assert engine.url.drivername == "postgresql+psycopg"


def test_hay_un_solo_engine_por_proceso() -> None:
    """Uno por petición agotaría las conexiones del dev server."""
    assert db.get_engine() is db.get_engine()


def test_pre_ping_activado() -> None:
    """La base vive tras Tailscale: una conexión muerta daría un 500 errático."""
    assert db.get_engine().pool._pre_ping is True


def test_el_pool_es_pequeno() -> None:
    """Laptop compartida por tres personas, cuatro servicios y el CI."""
    assert db.POOL_SIZE == 5
    assert db.MAX_OVERFLOW == 5


def test_la_url_sale_de_la_configuracion() -> None:
    """Ningún endpoint hardcodeado (§40).

    Se comparan las partes y no `str(url)`: SQLAlchemy enmascara la contraseña
    al serializar, precisamente para que no acabe en un log.
    """
    from apps.api.config import get_settings

    settings = get_settings()
    url = db.get_engine().url

    assert url.host == settings.postgres_host
    assert url.port == settings.postgres_port
    assert url.database == settings.postgres_db
    assert url.username == settings.postgres_user


def test_expire_on_commit_desactivado() -> None:
    """Serializar tras un commit no debe disparar una consulta por atributo."""
    assert db.get_sessionmaker().kw["expire_on_commit"] is False


def test_get_session_entrega_una_sesion() -> None:
    generador = db.get_session()
    session = next(generador)

    assert isinstance(session, Session)

    with pytest.raises(StopIteration):
        next(generador)


def test_el_cierre_hace_rollback_y_close_siempre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin el rollback, una transacción abierta volvería sucia al pool.

    El siguiente que tomara esa conexión heredaría el estado del anterior.
    """
    llamadas: list[str] = []
    monkeypatch.setattr(Session, "rollback", lambda self: llamadas.append("rollback"))
    monkeypatch.setattr(Session, "close", lambda self: llamadas.append("close"))

    list(db.get_session())

    assert llamadas == ["rollback", "close"]


def test_el_cierre_ocurre_aunque_el_endpoint_falle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El `finally` no es decorativo: una excepción no puede dejar la sesión abierta."""
    llamadas: list[str] = []
    monkeypatch.setattr(Session, "rollback", lambda self: llamadas.append("rollback"))
    monkeypatch.setattr(Session, "close", lambda self: llamadas.append("close"))

    generador = db.get_session()
    next(generador)
    with pytest.raises(RuntimeError):
        generador.throw(RuntimeError("el endpoint reventó"))

    assert llamadas == ["rollback", "close"]


def test_la_dependencia_no_hace_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirmar es decisión de quien escribe, no efecto de la dependencia."""
    commits: list[str] = []
    monkeypatch.setattr(Session, "commit", lambda self: commits.append("commit"))

    list(db.get_session())

    assert commits == []


def test_dispose_sin_engine_no_revienta() -> None:
    """Apagar la API sin haber consultado nada es normal, no un error."""
    db.dispose_engine()

    assert db.get_engine.cache_info().currsize == 0


def test_el_health_check_usa_el_engine_compartido() -> None:
    """Antes creaba uno desechable por sondeo, cuatro veces por petición."""
    from pathlib import Path

    fuente = Path("apps/api/routers/health.py").read_text(encoding="utf-8")

    assert "from apps.api.db import get_engine" in fuente
    assert "create_engine" not in fuente
