"""cuota del cable de acero: publicada en el DOF el 2026-04-09

Revision ID: e4b8c1d2f5a6
Revises: 9df25bf19e27
Create Date: 2026-10-13 23:30:00.000000+00:00

El #240 corrigió el cargador: `published_at` guardaba el inicio de la vigencia
(2024-12-17) y no la fecha en que el DOF publicó la resolución (2026-04-09,
expediente EC 32-24, ADR 0009). El cargador es idempotente y no toca las filas
ya cargadas, así que las cuatro de la compartida seguían mal. Esto las corrige.

Acotado a la URL de esa resolución y a las filas que aún tienen el defecto
(`published_at = valid_from`): una fila cargada después, ya correcta, no se toca.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e4b8c1d2f5a6"
down_revision: str | None = "9df25bf19e27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_URL = "https://dof.gob.mx/nota_detalle.php?codigo=5784426&fecha=09/04/2026"


def upgrade() -> None:
    op.execute(
        "UPDATE regulatory.compensatory_duties SET published_at = DATE '2026-04-09' "
        f"WHERE source_url = '{_URL}' AND published_at = valid_from"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE regulatory.compensatory_duties SET published_at = valid_from "
        f"WHERE source_url = '{_URL}' AND published_at = DATE '2026-04-09'"
    )
