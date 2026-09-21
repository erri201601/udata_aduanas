"""precio pagado e incrementables por partida

Revision ID: 9f5c85042bf1
Revises: 79d42f2e1bf2
Create Date: 2026-09-21 23:40:00+00:00

Levantado por Persona 3 el 21-sep, al ir a construir la comprobación de valor
del Pedimento Espejo: `pedimento_items` sólo guardaba `customs_value`, así que
no había contra qué contrastarlo. El espejo terminaba copiando el valor
declarado como valor esperado, y `VALUE_MISMATCH` no podía dispararse nunca.

NO ES UNA COLUMNA PARA EL BENCHMARK

Un pedimento real imprime las dos cosas por partida —«VAL ADU/USD» e «IMP.
PRECIO PAG.»—, y la Ley Aduanera (art. 65) llama incrementables a lo que se
suma al precio pagado para llegar al valor en aduana. No guardarlas era el
hueco; guardarlas es volver fiel al documento.

Con las tres, la comprobación es una resta que no necesita fuente externa:

    valor en aduana declarado == precio pagado + incrementables

En el corpus espejo V1 eso caza las seis anomalías de valor, que dejan la
cuenta rota a propósito con diferencias de entre 772 y 14 521 pesos.

Nullable a propósito: la partida que ya existe en la compartida no los tiene y
no se inventan. Una partida sin precio pagado no se puede comprobar, y eso es
un resultado legítimo —`unverifiable`— no un cero.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f5c85042bf1"
down_revision: str | None = "79d42f2e1bf2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA = "pedimento_items"
ESQUEMA = "operational"

#: Mismos tipos que `customs_value`: el dinero es Decimal, nunca float (regla 6).
COLUMNAS = (
    ("price_paid", sa.Numeric(18, 6)),
    ("price_paid_currency", sa.CHAR(3)),
    ("incrementables", sa.Numeric(18, 6)),
    ("incrementables_currency", sa.CHAR(3)),
)


def upgrade() -> None:
    for nombre, tipo in COLUMNAS:
        op.add_column(TABLA, sa.Column(nombre, tipo, nullable=True), schema=ESQUEMA)


def downgrade() -> None:
    for nombre, _ in reversed(COLUMNAS):
        op.drop_column(TABLA, nombre, schema=ESQUEMA)
