"""prosec_rates: la acotación forma parte de la clave

Revision ID: a7c3e91b2d40
Revises: 67e3c2617b54
Create Date: 2026-10-20 12:00:00.000000+00:00

El Decreto PROSEC lista la misma fracción dos veces en un sector, con
acotaciones opuestas y tasas distintas («Únicamente: …» al 5 %, «Excepto: …» al
10 %): 46 pares en la compilación de 2024. La clave `(sector, fracción,
valid_from)` del ADR 0011 no los admitía. `NULLS NOT DISTINCT` para que dos filas
sin acotación del mismo sector y fracción sigan chocando.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a7c3e91b2d40"
down_revision: str | None = "67e3c2617b54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_prosec_rates_fila", "prosec_rates", schema="regulatory", type_="unique")
    op.create_unique_constraint(
        "uq_prosec_rates_fila",
        "prosec_rates",
        ["sector_code", "fraction_code", "scope_note", "valid_from"],
        schema="regulatory",
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_constraint("uq_prosec_rates_fila", "prosec_rates", schema="regulatory", type_="unique")
    op.create_unique_constraint(
        "uq_prosec_rates_fila",
        "prosec_rates",
        ["sector_code", "fraction_code", "valid_from"],
        schema="regulatory",
    )
