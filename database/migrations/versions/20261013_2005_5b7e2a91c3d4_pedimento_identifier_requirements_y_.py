"""pedimento_identifier_requirements y pedimentos.identifiers

Revision ID: 5b7e2a91c3d4
Revises: c44d3d35f31f
Create Date: 2026-10-13 20:05:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5b7e2a91c3d4"
down_revision: str | None = "c44d3d35f31f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pedimento_identifier_requirements",
        sa.Column("identifier_code", sa.String(length=2), nullable=False),
        sa.Column(
            "identifier_level",
            sa.Enum(
                "G",
                "P",
                name="identifier_level",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "condition_kind",
            sa.Enum(
                "PEDIMENTO_KEY",
                "FRACTION",
                "NICO",
                name="identifier_condition",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("condition_value", sa.String(length=10), nullable=False),
        sa.Column("scope_note", sa.Text(), nullable=True),
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
            name=op.f("fk_pedimento_identifier_requirements_source_id_legal_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pedimento_identifier_requirements")),
        sa.UniqueConstraint(
            "identifier_code",
            "condition_kind",
            "condition_value",
            "valid_from",
            name="uq_pedimento_identifier_requirements_fila",
        ),
        schema="regulatory",
    )
    op.create_index(
        "ix_pedimento_identifier_requirements_vigencia",
        "pedimento_identifier_requirements",
        ["condition_kind", "condition_value", "valid_from", "valid_to"],
        unique=False,
        schema="regulatory",
    )
    op.add_column(
        "pedimentos",
        sa.Column(
            "identifiers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        schema="operational",
    )


def downgrade() -> None:
    op.drop_column("pedimentos", "identifiers", schema="operational")
    op.drop_index(
        "ix_pedimento_identifier_requirements_vigencia",
        table_name="pedimento_identifier_requirements",
        schema="regulatory",
    )
    op.drop_table("pedimento_identifier_requirements", schema="regulatory")
