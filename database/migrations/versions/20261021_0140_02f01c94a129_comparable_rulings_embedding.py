"""comparable_rulings: vector para ordenar por parecido (ADR 0019)

Revision ID: 02f01c94a129
Revises: 44a91d686797
Create Date: 2026-10-21 01:40:45.044324+00:00

Asunto más extracto literal de cada resolución, con el mismo proveedor y
la misma dimensión que `legal_chunks`. Nullable: sin vector se ordena por
fecha y la respuesta lo dice.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "02f01c94a129"
down_revision: str | None = "44a91d686797"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "comparable_rulings",
        sa.Column("embedding", Vector(1536), nullable=True),
        schema="regulatory",
    )


def downgrade() -> None:
    op.drop_column("comparable_rulings", "embedding", schema="regulatory")
