"""product_attributes.locator: dónde está cada dato dentro de su documento

El motor de Product DNA exige localización para OBSERVED y EXTRACTED
(`core/product_dna/engine.py`) y la tenía en memoria (`ExtractedAttribute.locator`),
pero al guardar se perdía. La evidencia de la extracción dice de qué archivo
salió la ficha; esta columna dice en qué parte de él está cada dato: «[p.3]
Especificaciones».

Sólo añade una columna nullable. No toca datos y es reversible.

Revision ID: 5b0c9e2d4a17
Revises: 8471a674f18d
Create Date: 2026-10-13 23:00:00.000000+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b0c9e2d4a17"
down_revision: str | None = "8471a674f18d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "product_attributes",
        sa.Column("locator", sa.Text(), nullable=True),
        schema="intelligence",
    )


def downgrade() -> None:
    op.drop_column("product_attributes", "locator", schema="intelligence")
