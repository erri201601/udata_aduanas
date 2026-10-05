"""opportunity_findings marca si es simulacion

`RiskFinding` traía `is_simulation` desde el principio y `OpportunityFinding`
no, aunque el repositorio se la pasaba a las dos. Resultado: `POST
/pedimentos/{id}/review` reventaba con un 500 en cuanto un pedimento producía
una oportunidad de ahorro. Pasa poco —de dieciséis pedimentos del corpus, uno—
y por eso llevaba meses escondido.

El 500 es el síntoma. El defecto es que un ahorro no podía decir si sale de una
operación inventada, y ése es el peor dato de la consola para no saberlo:
«puedes recuperar 17 400 pesos» leído de un pedimento de demo es la regla 4 al
revés —SYNTHETIC presentado como real— y encima en el campo que alguien querría
cobrar.

EL BACKFILL NO PUEDE SER `false` A SECAS

`false` significa «esto es real». Ponerlo por defecto en las filas existentes
afirmaría de golpe que todas las oportunidades guardadas describen operaciones
reales, que es exactamente la mentira que la columna viene a impedir. Se toma
de su pedimento, que sí lo sabe.

En ESTA base no hay ninguna fila que arreglar: el insert nunca llegó a
ejecutarse, así que la tabla está vacía. El backfill va igual, porque otra copia
de la base puede tenerlas y porque una migración que sólo funciona en la máquina
de quien la escribió no es una migración.

Las filas sin pedimento se quedan en `false` y no hay forma de hacerlo mejor:
un ahorro que no cuelga de ninguna operación no tiene de qué ser simulación.
Hoy no existe ninguna; si aparecen, el repositorio les pone el valor explícito.

Revision ID: 1e5763ec3eb6
Revises: 439320db3bdf
Create Date: 2026-10-05 03:46:01.954730+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1e5763ec3eb6"
down_revision: str | None = "439320db3bdf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "opportunity_findings",
        sa.Column("is_simulation", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="intelligence",
    )
    # Cada oportunidad hereda la marca de su pedimento: es el único sitio donde
    # consta, y es cierto por construcción —una oportunidad sobre una operación
    # simulada es una oportunidad simulada—.
    op.execute(
        sa.text("""
        UPDATE intelligence.opportunity_findings o
           SET is_simulation = p.is_simulation
          FROM operational.pedimentos p
         WHERE p.id = o.pedimento_id
        """)
    )


def downgrade() -> None:
    op.drop_column("opportunity_findings", "is_simulation", schema="intelligence")
