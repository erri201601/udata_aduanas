"""fusiona pedimento_identifiers y evidence_records rule_id/prompt_id

Revision ID: 3da38a88cc77
Revises: 23ad95925398, 16368c5161d1
Create Date: 2026-09-29 23:11:00.490450+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "3da38a88cc77"
down_revision: str | Sequence[str] | None = ("23ad95925398", "16368c5161d1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
