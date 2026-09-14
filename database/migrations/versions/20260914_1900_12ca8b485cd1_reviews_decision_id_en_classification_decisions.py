"""reviews_decision_id en classification_decisions: el veredicto dice qué revisó

Revision ID: 12ca8b485cd1
Revises: 5443e24b5a3f
Create Date: 2026-09-14 19:00:00+00:00

Persona 1, opción 1 (14-sep). Hasta ahora la métrica emparejaba cada veredicto
HUMAN_VALIDATED con «la última decisión de máquina del mismo DNA anterior al
veredicto». En la compartida hay un DNA con nueve decisiones y tres fechas de
operación: un veredicto sobre el caso de 2024 se comparaba contra la decisión
de 2026. Ahora el veredicto apunta a la decisión que revisó.

- FK autorreferencial, ON DELETE RESTRICT: una decisión revisada no se borra.
- UNIQUE: un solo veredicto por decisión, garantizado por la base. Sin índice
  aparte: el UNIQUE ya crea el suyo.
- CHECK: (data_origin = 'HUMAN_VALIDATED') = (reviews_decision_id IS NOT NULL).

Sin backfill: el 14-sep la compartida tiene 0 filas HUMAN_VALIDATED (9, todas
SYNTHETIC), así que el CHECK se cumple al crearse.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "12ca8b485cd1"
down_revision: str | None = "5443e24b5a3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classification_decisions",
        sa.Column("reviews_decision_id", sa.Uuid(), nullable=True),
        schema="intelligence",
    )
    op.create_foreign_key(
        op.f("fk_classification_decisions_reviews_decision_id_classification_decisions"),
        "classification_decisions",
        "classification_decisions",
        ["reviews_decision_id"],
        ["id"],
        source_schema="intelligence",
        referent_schema="intelligence",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        op.f("uq_classification_decisions_reviews_decision_id"),
        "classification_decisions",
        ["reviews_decision_id"],
        schema="intelligence",
    )
    op.create_check_constraint(
        op.f("ck_classification_decisions_revision_dice_que_revisa"),
        "classification_decisions",
        "(data_origin = 'HUMAN_VALIDATED') = (reviews_decision_id IS NOT NULL)",
        schema="intelligence",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_classification_decisions_revision_dice_que_revisa"),
        "classification_decisions",
        schema="intelligence",
        type_="check",
    )
    op.drop_constraint(
        op.f("uq_classification_decisions_reviews_decision_id"),
        "classification_decisions",
        schema="intelligence",
        type_="unique",
    )
    op.drop_constraint(
        op.f("fk_classification_decisions_reviews_decision_id_classification_decisions"),
        "classification_decisions",
        schema="intelligence",
        type_="foreignkey",
    )
    op.drop_column("classification_decisions", "reviews_decision_id", schema="intelligence")
