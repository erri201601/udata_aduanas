"""evidence_records guarda rule_id y prompt_id

Dos columnas aditivas y nullables. No hay backfill: la traza de la decisión
lleva las reglas en orden y las evidencias se escriben en ese mismo orden, así
que emparejarlas por posición parece tentador y sería reconstruir fundamento a
partir de una coincidencia de inserción. Las filas anteriores se quedan en
NULL, y el dossier las declara sin responder (regla 1 de CLAUDE.md).

Revision ID: 23ad95925398
Revises: 4612fe2efe9e
Create Date: 2026-09-29 18:37:33.691572+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "23ad95925398"
down_revision: str | None = "4612fe2efe9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence_records",
        sa.Column("rule_id", sa.String(length=16), nullable=True),
        schema="intelligence",
    )
    op.add_column(
        "evidence_records", sa.Column("prompt_id", sa.Text(), nullable=True), schema="intelligence"
    )


def downgrade() -> None:
    op.drop_column("evidence_records", "prompt_id", schema="intelligence")
    op.drop_column("evidence_records", "rule_id", schema="intelligence")
