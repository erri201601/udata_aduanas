"""trade_statistics: cifras abiertas del SAT por mes (ADR 0021)

Revision ID: df0a46c2656c
Revises: 02f01c94a129
Create Date: 2026-10-21 02:12:03.776987+00:00

Pedimentos pagados y recaudación de comercio exterior. Referencia para
calibrar y comparar; ningún motor calcula dinero con ellas.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "df0a46c2656c"
down_revision: str | None = "02f01c94a129"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trade_statistics",
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("series", sa.String(length=64), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("value", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("is_cumulative", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "data_origin",
            sa.Enum(
                "OFFICIAL",
                "PUBLIC",
                "LICENSED",
                "SYNTHETIC",
                "HUMAN_VALIDATED",
                name="data_origin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_document", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["regulatory.legal_sources.id"],
            name=op.f("fk_trade_statistics_source_id_legal_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_statistics")),
        sa.UniqueConstraint("source", "series", "year", "month", name="uq_trade_statistics_fila"),
        schema="regulatory",
    )
    op.create_index(
        "ix_trade_statistics_vigencia",
        "trade_statistics",
        ["source", "series", "valid_from", "valid_to"],
        unique=False,
        schema="regulatory",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trade_statistics_vigencia", table_name="trade_statistics", schema="regulatory"
    )
    op.drop_table("trade_statistics", schema="regulatory")
