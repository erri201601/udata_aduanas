"""tres tipos de error más para el Ground Truth (§25 ampliado)

Revision ID: 79d42f2e1bf2
Revises: 12ca8b485cd1
Create Date: 2026-09-21 22:35:00+00:00

Aprobado por Persona 1 el 21-sep-2026, al validar el corpus espejo V1 (15
pedimentos, 180 partidas, 60 anomalías sembradas). El §25 dice «implementar
inicialmente» esos diez tipos, así que la lista admite crecer; lo que no
admite es crecer sola.

SIETE DE LOS DIEZ TIPOS DEL CORPUS YA TENÍAN CASA

    FRACCION_INCORRECTA        -> WRONG_FRACTION
    NICO_INCORRECTO            -> WRONG_NICO
    PAIS_ORIGEN_INCONSISTENTE  -> WRONG_ORIGIN
    IGI_TASA_INCORRECTA        -> WRONG_VALUE + expected_field='igi_rate'
    IVA_BASE_INCORRECTA        -> WRONG_VALUE + expected_field='iva_base'
    IVA_IMPORTE_INCORRECTO     -> WRONG_VALUE + expected_field='iva_amount'
    VALOR_ADUANA_INCONSISTENTE -> WRONG_VALUE + expected_field='customs_value'

Los cuatro fiscales caben en `WRONG_VALUE` porque `expected_field` ya guarda
QUÉ campo está mal: crear un tipo por concepto habría duplicado esa columna.

LOS TRES QUE NO CABÍAN, Y POR QUÉ

    WRONG_UNIT               una UMC que no existe en el Anexo 22 no es un
                             valor equivocado: es una clave inexistente.
    INCONSISTENT_QUANTITY    la cantidad no cuadra con el resto de la
                             partida; no hay dinero mal, hay cantidad mal.
    MISSING_TECHNICAL_FIELD  falta la característica que permite clasificar.
                             `MISSING_INCREMENTABLE` es de valor en aduana,
                             no de descripción de mercancía.

La columna sigue siendo VARCHAR(31): el más largo de los tres nuevos mide 23
y `INCONSISTENT_SKU_CLASSIFICATION` ya medía 31. Sólo cambia el CHECK.

Detalle que cuesta una hora si no se sabe: a `op.drop_constraint` se le pasa
el nombre LÓGICO («error_type»), porque la convención de nombres del proyecto
le antepone «ck_<tabla>_». Con el nombre físico completo, Alembic lo duplica.

`downgrade()` recrea el CHECK anterior. Si para entonces existen filas con
los tipos nuevos, PostgreSQL rechaza la restricción y la migración falla: es
lo correcto, porque volver atrás con esos datos cargados los invalidaría en
silencio.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "79d42f2e1bf2"
down_revision: str | None = "12ca8b485cd1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: El nombre LÓGICO, no el físico. `NAMING_CONVENTION` en database/models/base.py
#: define `ck` como `ck_%(table_name)s_%(constraint_name)s`, así que Alembic
#: compone `ck_ground_truth_records_error_type` a partir de esto. Pasarle el
#: nombre completo produce `ck_ground_truth_records_ck_ground_truth_records_
#: error_type` y la migración muere buscando una restricción que no existe.
RESTRICCION = "error_type"
TABLA = "ground_truth_records"
ESQUEMA = "intelligence"

ANTES = (
    "WRONG_FRACTION",
    "WRONG_NICO",
    "WRONG_ORIGIN",
    "MISSING_NOM",
    "MISSED_PROSEC",
    "MISSED_PREFERENCE",
    "WRONG_VALUE",
    "MISSING_INCREMENTABLE",
    "WRONG_IDENTIFIER",
    "INCONSISTENT_SKU_CLASSIFICATION",
)
DESPUES = (*ANTES, "WRONG_UNIT", "INCONSISTENT_QUANTITY", "MISSING_TECHNICAL_FIELD")


def _condicion(valores: tuple[str, ...]) -> sa.TextClause:
    return sa.text("error_type IN (" + ", ".join(f"'{v}'" for v in valores) + ")")


def _reemplazar(valores: tuple[str, ...]) -> None:
    op.drop_constraint(RESTRICCION, TABLA, schema=ESQUEMA, type_="check")
    op.create_check_constraint(RESTRICCION, TABLA, _condicion(valores), schema=ESQUEMA)


def upgrade() -> None:
    _reemplazar(DESPUES)


def downgrade() -> None:
    _reemplazar(ANTES)
