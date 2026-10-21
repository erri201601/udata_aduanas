"""trade_statistics.value: ocho decimales, los centavos de millones de pesos

Revision ID: ecedec726d14
Revises: df0a46c2656c
Create Date: 2026-10-21 02:18:08.803044+00:00

Con seis decimales la base redondeaba los centavos de la recaudación (que el
SAT publica en millones de pesos) y cada recarga contaba cifras «cambiadas».
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ecedec726d14"
down_revision: str | None = "df0a46c2656c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "trade_statistics",
        "value",
        existing_type=sa.NUMERIC(precision=20, scale=6),
        type_=sa.Numeric(precision=24, scale=8),
        existing_nullable=False,
        schema="regulatory",
    )


def downgrade() -> None:
    op.alter_column(
        "trade_statistics",
        "value",
        existing_type=sa.Numeric(precision=24, scale=8),
        type_=sa.NUMERIC(precision=20, scale=6),
        existing_nullable=False,
        schema="regulatory",
    )
