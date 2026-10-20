"""comparable_rulings: casos comparables de otras aduanas (ADR 0019)

Revision ID: 44a91d686797
Revises: 34221774f8f9
Create Date: 2026-10-20 22:52:51.039753+00:00

Resoluciones de clasificación de CBP (y, más adelante, EBTI): casos
comparables, nunca fundamento jurídico mexicano. Tabla aparte de
`legal_chunks` para que el RAG jurídico no las cite como ley.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "44a91d686797"
down_revision: str | None = "34221774f8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comparable_rulings",
        sa.Column("authority", sa.String(length=16), nullable=False),
        sa.Column("ruling_number", sa.String(length=32), nullable=False),
        sa.Column("collection", sa.String(length=16), nullable=True),
        sa.Column("ruling_date", sa.Date(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("categories", sa.Text(), nullable=True),
        sa.Column(
            "tariff_codes",
            postgresql.ARRAY(sa.String(length=32)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "hs6_codes", postgresql.ARRAY(sa.String(length=6)), server_default="{}", nullable=False
        ),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "revoked_by",
            postgresql.ARRAY(sa.String(length=32)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "modified_by",
            postgresql.ARRAY(sa.String(length=32)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "related_rulings",
            postgresql.ARRAY(sa.String(length=32)),
            server_default="{}",
            nullable=False,
        ),
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
            name=op.f("fk_comparable_rulings_source_id_legal_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comparable_rulings")),
        sa.UniqueConstraint("authority", "ruling_number", name="uq_comparable_rulings_fila"),
        schema="regulatory",
    )
    op.create_index(
        "ix_comparable_rulings_hs6",
        "comparable_rulings",
        ["hs6_codes"],
        unique=False,
        schema="regulatory",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_comparable_rulings_vigencia",
        "comparable_rulings",
        ["authority", "ruling_number", "valid_from", "valid_to"],
        unique=False,
        schema="regulatory",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_comparable_rulings_vigencia", table_name="comparable_rulings", schema="regulatory"
    )
    op.drop_index(
        "ix_comparable_rulings_hs6",
        table_name="comparable_rulings",
        schema="regulatory",
        postgresql_using="gin",
    )
    op.drop_table("comparable_rulings", schema="regulatory")
