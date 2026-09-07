"""Entorno de Alembic para ADUANERO OS.

La URL de conexión se toma de `apps.api.config.Settings`, es decir de `.env`.
Nunca se escribe en alembic.ini (§40 maestro).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from apps.api.config import get_settings
from database.models import Base
from sqlalchemy import CheckConstraint, engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# La URL viene de .env, no del ini.
config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_url)

target_metadata = Base.metadata

# Esquemas propios del proyecto; los del sistema se ignoran al autogenerar.
PROJECT_SCHEMAS = {"public", "raw", "regulatory", "operational", "intelligence"}


def include_object(obj, name, type_, reflected, compare_to) -> bool:  # type: ignore[no-untyped-def]
    """Excluye del autogenerado lo que no pertenece al proyecto.

    Sin esto, `alembic revision --autogenerate` propone borrar las tablas de
    extensiones como pgvector.
    """
    if type_ == "table":
        schema = getattr(obj, "schema", None) or "public"
        if schema not in PROJECT_SCHEMAS:
            return False
    # Alembic 1.19 no empareja los CHECK creados por Enum(native_enum=False)
    # con su equivalente en la metadata y propone borrarlos en la migración
    # siguiente. Si existe el mismo CHECK nombrado en el modelo, se conserva.
    if type_ == "check_constraint" and reflected and compare_to is None:
        table = obj.table
        table_key = f"{table.schema}.{table.name}" if table.schema else table.name
        metadata_table = target_metadata.tables.get(table_key)
        if metadata_table is not None and any(
            isinstance(constraint, CheckConstraint) and constraint.name == name
            for constraint in metadata_table.constraints
        ):
            return False
    return True


def run_migrations_offline() -> None:
    """Genera SQL sin conectarse a la base."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica las migraciones contra la base real."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
