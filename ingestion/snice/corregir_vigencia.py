"""La LIGIE 2022 rige desde el 12-dic-2022, no desde su publicación (ADR 0018).

Todo lo que se cargó de la LIGIE 2022 empezaba su vigencia el 2022-06-07, que
es la fecha de PUBLICACIÓN en el DOF. El Transitorio Primero del decreto la
hace entrar en vigor diez días después de que el SAT declare listos sus
sistemas. La Cuarta Resolución de Modificaciones a las RGCE 2022 (DOF
5-dic-2022, punto SEGUNDO) lo declaró: «entrará en vigor el 12 de diciembre de
2022».

Con la fecha de publicación, una operación de junio a diciembre de 2022 se
evaluaba con una ley que aún no regía (regla 5). Este módulo corre la vigencia
de esas filas al 2022-12-12 y deja la publicación en `published_at`, donde le
corresponde. No borra ni crea filas: los `id` no cambian, así que las
decisiones que apuntan a una fracción o a un NICO siguen apuntando a la misma.

Es una corrección versionada, no SQL a mano: queda en el repositorio, con
tests, y correrla dos veces no cambia nada.

Uso:
    python -m ingestion.snice.corregir_vigencia --target local --dry-run
    python -m ingestion.snice.corregir_vigencia --target local
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from apps.api.logging import con_corrida, registrar
from database.models import (
    LegalChunkRecord,
    LegalDocument,
    LegalRule,
    Nico,
    TariffFraction,
    TariffHeading,
    TariffHeadingGroup,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.snice.load import LIGIE_PUBLISHED_AT, LIGIE_VALID_FROM

if TYPE_CHECKING:
    from datetime import date
    from typing import Any

log = structlog.stdlib.get_logger("ingestion.snice.corregir_vigencia")

#: Lo que se cargó con la fecha de publicación como inicio de vigencia.
FECHA_EQUIVOCADA: Final = LIGIE_PUBLISHED_AT

TABLAS: Final[tuple[Any, ...]] = (
    TariffFraction,
    Nico,
    TariffHeading,
    TariffHeadingGroup,
    LegalDocument,
    LegalRule,
    LegalChunkRecord,
)


def corregir(session: Session, *, desde: date = LIGIE_VALID_FROM) -> dict[str, int]:
    """Corre al `desde` la vigencia de lo cargado con la fecha de publicación.

    Lo SINTÉTICO no se toca: no viene de la ley. Devuelve cuántas filas se
    corrigieron por tabla.
    """
    corregidas: dict[str, int] = {}
    for modelo in TABLAS:
        donde = sa.and_(
            modelo.valid_from == FECHA_EQUIVOCADA,
            modelo.data_origin != "SYNTHETIC",
        )
        n = session.scalar(sa.select(sa.func.count()).select_from(modelo).where(donde)) or 0
        if n:
            session.execute(
                sa.update(modelo)
                .where(donde)
                .values(
                    valid_from=desde,
                    published_at=sa.func.coalesce(modelo.published_at, FECHA_EQUIVOCADA),
                )
                .execution_options(synchronize_session=False)
            )
        corregidas[modelo.__tablename__] = n
    session.flush()
    log.info("snice.vigencia_ligie.corregida", desde=str(desde), **corregidas)
    return corregidas


@con_corrida("ingestion.snice.corregir_vigencia")
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["local"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    with Session(create_engine(get_settings().sqlalchemy_url)) as session:
        corregidas = corregir(session)
        total = sum(corregidas.values())
        registrar(records=total)
        for tabla, n in corregidas.items():
            print(f"  {tabla:24} {n}")
        if args.dry_run:
            session.rollback()
            print(f"--dry-run: {total} filas se corregirían; revertido.")
        else:
            session.commit()
            print(
                f"OK ({args.target}): {total} filas de la LIGIE 2022 rigen desde {LIGIE_VALID_FROM}."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
