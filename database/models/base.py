"""Base declarativa de SQLAlchemy para ADUANERO OS.

Sprint 0 sólo define la base y la convención de nombres de constraints, para
que Alembic genere migraciones deterministas y reversibles.

Las 23 entidades del Canonical Data Model (§8 Persona 1) llegan en el PR
siguiente. No añadir modelos aquí sin aprobación de Persona 1 (§10.9).
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Nombres explícitos de constraints. Sin esto, Alembic genera nombres
# autogenerados que impiden escribir un downgrade fiable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Esquemas creados por infrastructure/docker/postgres/init/01_extensions.sql.
# Alembic los ignora al autogenerar salvo que un modelo los declare.
SCHEMAS = ("raw", "regulatory", "operational", "intelligence")


class Base(DeclarativeBase):
    """Base declarativa común a todos los modelos del Canonical Data Model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
