"""regulatory_events: hash de la nota leída (ADR 0022)

Revision ID: 7f5c0b396d7f
Revises: ecedec726d14
Create Date: 2026-10-21 16:49:31.724909+00:00

De qué nota del DOF salieron las fracciones, las NOM y la entrada en vigor
de un evento. NULL = la nota aún no se leyó: los campos vacíos no dicen
«no afecta», dicen «no se sabe todavía».
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f5c0b396d7f"
down_revision: str | None = "ecedec726d14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "regulatory_events",
        sa.Column("note_content_hash", sa.Text(), nullable=True),
        schema="regulatory",
    )


def downgrade() -> None:
    op.drop_column("regulatory_events", "note_content_hash", schema="regulatory")
