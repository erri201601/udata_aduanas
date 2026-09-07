"""Sesión de base de datos para los routers.

SÍNCRONA a propósito. No hay una sola línea async en el repo: `health.py`
sondea con `create_engine` dentro de `asyncio.to_thread`, y los tests y los
seeds usan `Session` con psycopg. Meter `AsyncSession` crearía dos mundos, y
los errores de greenlet que aparecen al mezclarlos son de los peores de
diagnosticar — se manifiestan lejos de donde está la causa.

USO

    from apps.api.db import SessionDep

    @router.get("/products")
    def listar(session: SessionDep) -> list[ProductRead]:
        return [ProductRead.model_validate(p) for p in session.scalars(select(Product))]

El engine se crea la primera vez que alguien lo pide, no al importar. Eso
conserva la regla que ya fijaba el `lifespan` —"no abre conexiones: eso lo
decide cada router"— y deja que la API arranque sin PostgreSQL, que es la
situación de cualquiera que trabaje sin la infraestructura del dev server.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

# El dev server es una laptop compartida por tres personas, cuatro servicios y
# el CI. Un pool grande no da rendimiento: agota las conexiones de PostgreSQL.
POOL_SIZE = 5
MAX_OVERFLOW = 5


@lru_cache
def get_engine() -> Engine:
    """Engine único del proceso, creado la primera vez que se pide.

    `pool_pre_ping` porque la base vive al otro lado de Tailscale: una conexión
    del pool puede haber muerto entre peticiones sin que el proceso se entere,
    y el síntoma sería un 500 intermitente imposible de reproducir.
    """
    return create_engine(
        get_settings().sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """Fábrica de sesiones ligada al engine del proceso.

    `expire_on_commit=False` para que los objetos sigan siendo legibles después
    de confirmar: sin esto, serializar una respuesta tras un commit dispara una
    consulta nueva por cada atributo, y con la sesión ya cerrada eso revienta.
    """
    return sessionmaker(bind=get_engine(), class_=Session, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición.

    El `rollback()` del cierre es explícito y siempre se ejecuta. Si el
    endpoint confirmó, no hace nada; si falló a medias, descarta lo pendiente
    y la conexión vuelve limpia al pool. Sin él, una transacción abierta
    regresaría al pool y el siguiente que la tomara heredaría ese estado.

    No hace commit: cuando existan endpoints de escritura, confirmar debe ser
    una decisión explícita de quien escribe, no un efecto de la dependencia.
    """
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def dispose_engine() -> None:
    """Cierra el pool al apagar la aplicación.

    Tolera no haber abierto nunca una conexión: si nadie pidió una sesión, el
    engine no existe y no hay nada que cerrar.
    """
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
