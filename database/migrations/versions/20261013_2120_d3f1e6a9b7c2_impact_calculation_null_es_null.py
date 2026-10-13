"""impact_calculation: el JSON null pasa a NULL de SQL

Revision ID: d3f1e6a9b7c2
Revises: c8a2a253f2b1
Create Date: 2026-10-13 21:20:00.000000+00:00

La columna se creó sin `none_as_null` y las filas sin monto guardaron el JSON
`null` en vez de `NULL`. Con eso `impact_calculation IS NULL` no distinguía
«sin cálculo». El modelo ya escribe `NULL`; esto normaliza lo ya escrito.

El downgrade no lo deshace: devolver un `null` JSON sería reintroducir el
defecto, y las dos formas significan lo mismo para quien lee la columna.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d3f1e6a9b7c2"
down_revision: str | None = "c8a2a253f2b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE intelligence.risk_findings SET impact_calculation = NULL "
        "WHERE impact_calculation = 'null'::jsonb"
    )


def downgrade() -> None:
    # Sin operación a propósito: ver el docstring.
    op.execute("SELECT 1")
