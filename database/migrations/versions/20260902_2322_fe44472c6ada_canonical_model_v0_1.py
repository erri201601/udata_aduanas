"""canonical model v0.1

Revision ID: fe44472c6ada
Revises:
Create Date: 2026-09-02 23:22:50.940195+00:00

Crea las 23 entidades del Canonical Data Model (§8 Persona 1 / §4 TAREA_P2) en
los esquemas `regulatory`, `operational` e `intelligence`.

NOTA DE MÉTODO (revisar con Persona 1): esta primera migración materializa el
esquema desde `database.models.Base.metadata` en vez de con `op.create_table`
explícito. Motivo: el entorno donde se redactó no tiene acceso a un PostgreSQL
y `alembic revision --autogenerate` exige conexión. La ventaja es que la
migración no puede divergir de los modelos. `downgrade()` es real y reversible.
A partir de 0002, todo cambio de esquema va con operaciones `op.*` explícitas
(§10.4 Persona 1).

Verificación pendiente (requiere Docker/Postgres local):
    alembic upgrade head && alembic downgrade base && alembic upgrade head
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from database.models import Base
from sqlalchemy.schema import CreateSchema

revision: str = "fe44472c6ada"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Esquemas que tocan las 23 tablas. `raw` (landing de ingestión) llega aparte.
_SCHEMAS: tuple[str, ...] = ("regulatory", "operational", "intelligence")


def upgrade() -> None:
    bind = op.get_bind()
    for schema in _SCHEMAS:
        op.execute(CreateSchema(schema, if_not_exists=True))
    # gen_random_uuid() es core en PostgreSQL 13+ (imagen pgvector/pgvector:pg16).
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Sólo se eliminan las 23 tablas. Los esquemas los crea también la infra
    # (infrastructure/docker/postgres/init) — no son de esta migración.
    Base.metadata.drop_all(bind=op.get_bind())
