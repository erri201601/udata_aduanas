"""Configuración de ADUANERO OS.

Fuente única de verdad para las conexiones. Se lee de variables de entorno /
`.env`. Ningún secreto se escribe aquí (§40 maestro, §10.10 Persona 1).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración de la aplicación, cargada desde entorno o `.env`."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Aplicación ───────────────────────────────────────────────────────────
    app_name: str = "aduanero-os"
    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ── API ──────────────────────────────────────────────────────────────────
    # 8080 y no 8000: el 8000 está ocupado por otro proyecto en el dev server.
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    api_secret_key: SecretStr = SecretStr("")

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    # 5433 y no 5432: el 5432 lo ocupa un PostgreSQL nativo ajeno al proyecto.
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "aduanero"
    postgres_user: str = "aduanero_app"
    postgres_password: SecretStr = SecretStr("")
    database_url: str | None = None

    # ── Neo4j ────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: SecretStr = SecretStr("")
    redis_url: str | None = None

    # ── MinIO ────────────────────────────────────────────────────────────────
    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "aduanero_minio"
    minio_root_password: SecretStr = SecretStr("")
    minio_bucket_raw: str = "aduanero-raw"
    minio_bucket_docs: str = "aduanero-docs"
    minio_secure: bool = False

    # ── Proveedores de IA (§29: el dominio nunca importa un SDK concreto) ─────
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    google_api_key: SecretStr = SecretStr("")
    default_model_provider: str = Field(default="anthropic")

    # ── Derivados ────────────────────────────────────────────────────────────
    # repr=False es deliberado: la URL lleva la contraseña en claro y los
    # computed_field entran en repr() por defecto, que es como un secreto
    # acaba en un traceback o en un log (§40 maestro).
    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        """URL de SQLAlchemy. `DATABASE_URL` explícita gana sobre las partes."""
        if self.database_url:
            return self.database_url
        pwd = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pwd}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field(repr=False)  # type: ignore[prop-decorator]
    @property
    def effective_redis_url(self) -> str:
        """URL de Redis. `REDIS_URL` explícita gana sobre las partes."""
        if self.redis_url:
            return self.redis_url
        pwd = self.redis_password.get_secret_value()
        auth = f":{pwd}@" if pwd else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/0"


class UrlCompartidaAusenteError(RuntimeError):
    """Se pidió la base del equipo y `ADUANERO_SHARED_URL` no está definida."""


def url_de_postgres(target: str) -> str:
    """De dónde se lee Postgres: la de esta máquina, o la del equipo.

    LA BASE DEL EQUIPO NO ES NUESTRA Y NO SE DUPLICA

    Vive en la laptop de Persona 1 (`udata-nitro`) y sólo se alcanza por
    Tailscale. Nadie levanta una segunda: dos bases serían dos verdades, y la
    métrica dejaría de decir algo sobre el sistema.

    Su contraseña NO está en `.env` ni en el código. Se pasa por entorno en la
    sesión que la necesita y se entrega por canal seguro (§40). Si falta, se
    dice y se sale: un valor por omisión aquí sería una credencial en el
    repositorio.

    DESDE LA LAPTOP DE PERSONA 1, 'local' YA ES LA DEL EQUIPO. Allí 'shared'
    falla pidiendo una variable que en esa máquina no existe.
    """
    if target == "shared":
        url = os.environ.get("ADUANERO_SHARED_URL")
        if not url:
            raise UrlCompartidaAusenteError(
                "ADUANERO_SHARED_URL no está definida. La contraseña la entrega "
                "Persona 1 por canal seguro — nunca por chat ni en el código."
            )
        return url
    return get_settings().sqlalchemy_url


@lru_cache
def get_settings() -> Settings:
    """Settings cacheadas — se leen una sola vez por proceso.

    El fichero se resuelve aquí y no en `model_config` para que sea sustituible:
    `ADUANERO_ENV_FILE=.env.staging` apunta a otro entorno y `ADUANERO_ENV_FILE=`
    (vacío) desactiva la lectura de fichero, que es lo que hacen los tests para
    no heredar las credenciales reales del desarrollador.
    """
    env_file = os.getenv("ADUANERO_ENV_FILE", ".env")
    return Settings(_env_file=env_file or None)  # type: ignore[call-arg]
