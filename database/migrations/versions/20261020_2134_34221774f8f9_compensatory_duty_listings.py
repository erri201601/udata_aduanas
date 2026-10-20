"""compensatory_duty_listings: el Anexo 2.5.1 como índice (ADR 0017)

Revision ID: 34221774f8f9
Revises: b4d2e8f17a3c
Create Date: 2026-10-20 21:34:35.235746+00:00

Dónde hay cuota compensatoria según el Anexo 2.5.1 (DOF 25-nov-2022). La cuota
se guarda como texto, no como número: la regla 2.5.3 hace prevalecer la
resolución sobre el anexo, y el importe sigue saliendo de `compensatory_duties`
(ADR 0009). La clave incluye la primera resolución porque hay dos cuotas
distintas sobre la misma fracción y origen.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "34221774f8f9"
down_revision: str | None = "b4d2e8f17a3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compensatory_duty_listings",
        sa.Column("product_description", sa.Text(), nullable=False),
        sa.Column("fraction_code", sa.String(length=8), nullable=False),
        sa.Column("origin_country", sa.String(length=2), nullable=False),
        sa.Column("exporter_text", sa.Text(), nullable=True),
        sa.Column("applies_to_all_others", sa.Boolean(), nullable=False),
        sa.Column("duty_text", sa.Text(), nullable=False),
        sa.Column("scope_note", sa.Text(), nullable=True),
        sa.Column("resolution_history", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_resolution_date", sa.Date(), nullable=True),
        sa.Column("latest_resolution_date", sa.Date(), nullable=True),
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
            name=op.f("fk_compensatory_duty_listings_source_id_legal_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compensatory_duty_listings")),
        sa.UniqueConstraint(
            "fraction_code",
            "origin_country",
            "product_description",
            "exporter_text",
            "first_resolution_date",
            "valid_from",
            name="uq_compensatory_duty_listings_fila",
            postgresql_nulls_not_distinct=True,
        ),
        schema="regulatory",
    )
    op.create_index(
        "ix_compensatory_duty_listings_consulta",
        "compensatory_duty_listings",
        ["origin_country", "fraction_code", "valid_from", "valid_to"],
        unique=False,
        schema="regulatory",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_compensatory_duty_listings_consulta",
        table_name="compensatory_duty_listings",
        schema="regulatory",
    )
    op.drop_table("compensatory_duty_listings", schema="regulatory")
