"""merge heads: identificadores de pedimento texto + decision vigente de ficha

Revision ID: 8d0c36b5f879
Revises: d9fc5116df71, cf43374650ac
Create Date: 2026-10-06 21:10:40.406607+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "8d0c36b5f879"
down_revision: str | Sequence[str] | None = ("d9fc5116df71", "cf43374650ac")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
