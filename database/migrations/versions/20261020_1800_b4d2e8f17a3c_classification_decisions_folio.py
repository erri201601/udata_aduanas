"""classification_decisions: folio legible AD-AAAA-NNNNNN (§17)

Revision ID: b4d2e8f17a3c
Revises: a7c3e91b2d40
Create Date: 2026-10-20 18:00:00.000000+00:00

§17 del maestro identifica cada decisión como `AD-2026-000001`. Un UUID no se
dicta por teléfono ni se cita en un dictamen; un folio sí. Lo asigna la base
(una secuencia y el año de emisión en la Ciudad de México) para que dos
escrituras concurrentes nunca choquen, y las decisiones que ya existen lo
reciben en orden de creación con el año en que se emitieron (ADR 0015).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d2e8f17a3c"
down_revision: str | None = "a7c3e91b2d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# El año es el de la Ciudad de México, no el de la sesión: con `TimeZone` del
# cliente, una decisión emitida la Nochevieja cambiaría de año según quién la
# escriba.
#
# `lpad` recorta lo que pasa del ancho: con 6 fijos, la decisión 1 000 000
# saldría con el folio de la 100 000. El ancho crece con el número.
FUNCION = """
CREATE FUNCTION intelligence.siguiente_folio_de_decision() RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE n bigint := nextval('intelligence.classification_decision_folio_seq');
BEGIN
    RETURN 'AD-' || to_char(now() AT TIME ZONE 'America/Mexico_City', 'YYYY') || '-'
        || lpad(n::text, greatest(6, length(n::text)), '0');
END $$
"""


def upgrade() -> None:
    op.execute("CREATE SEQUENCE intelligence.classification_decision_folio_seq")
    op.execute(FUNCION)
    op.add_column(
        "classification_decisions",
        sa.Column("folio", sa.String(length=24), nullable=True),
        schema="intelligence",
    )
    op.execute(
        """
        WITH orden AS (
            SELECT id, created_at,
                   row_number() OVER (ORDER BY created_at, id) AS n
            FROM intelligence.classification_decisions
        )
        UPDATE intelligence.classification_decisions d
        SET folio = 'AD-'
                 || to_char(o.created_at AT TIME ZONE 'America/Mexico_City', 'YYYY') || '-'
                 || lpad(o.n::text, greatest(6, length(o.n::text)), '0')
        FROM orden o WHERE o.id = d.id
        """
    )
    op.execute(
        "SELECT setval('intelligence.classification_decision_folio_seq', "
        "greatest(1, (SELECT count(*) FROM intelligence.classification_decisions)), "
        "(SELECT count(*) > 0 FROM intelligence.classification_decisions))"
    )
    op.alter_column(
        "classification_decisions",
        "folio",
        nullable=False,
        server_default=sa.text("intelligence.siguiente_folio_de_decision()"),
        schema="intelligence",
    )
    op.create_unique_constraint(
        "uq_classification_decisions_folio",
        "classification_decisions",
        ["folio"],
        schema="intelligence",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_classification_decisions_folio",
        "classification_decisions",
        schema="intelligence",
        type_="unique",
    )
    op.drop_column("classification_decisions", "folio", schema="intelligence")
    op.execute("DROP FUNCTION intelligence.siguiente_folio_de_decision()")
    op.execute("DROP SEQUENCE intelligence.classification_decision_folio_seq")
