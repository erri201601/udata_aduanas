"""peso neto por partida y rectificacion de pedimentos

Revision ID: 67e3c2617b54
Revises: 88cd0fb12273
Create Date: 2026-10-13 20:01:40.417738+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "67e3c2617b54"
down_revision: str | None = "88cd0fb12273"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pedimento_items",
        sa.Column("net_weight_kg", sa.Numeric(precision=18, scale=6), nullable=True),
        schema="operational",
    )
    op.add_column(
        "pedimentos",
        sa.Column("rectifies_pedimento_id", sa.Uuid(), nullable=True),
        schema="operational",
    )
    op.add_column(
        "pedimentos",
        sa.Column("rectification_number", sa.SmallInteger(), nullable=True),
        schema="operational",
    )
    op.create_foreign_key(
        op.f("fk_pedimentos_rectifies_pedimento_id_pedimentos"),
        "pedimentos",
        "pedimentos",
        ["rectifies_pedimento_id"],
        ["id"],
        source_schema="operational",
        referent_schema="operational",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_pedimentos_rectifies_pedimento_id_pedimentos"),
        "pedimentos",
        schema="operational",
        type_="foreignkey",
    )
    op.drop_column("pedimentos", "rectification_number", schema="operational")
    op.drop_column("pedimentos", "rectifies_pedimento_id", schema="operational")
    op.drop_column("pedimento_items", "net_weight_kg", schema="operational")
