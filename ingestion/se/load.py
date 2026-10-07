"""PARSED -> DATABASE del Anexo 2.4.1.

El RAW ya está en MinIO con su hash antes de llegar aquí (§12). Esta parte sólo
escribe lo que el parser entendió, y **no carga lo que no pudo verificar**: una
fila sin NOM legible no se guarda como si no exigiera nada — simplemente no se
guarda, y la fracción sigue sin correlación conocida.

La diferencia importa: `required_nom_codes = ()` afirma «no exige ninguna» y
permite declarar la partida limpia. `None` dice «no lo sé». Cargar de menos
deja `None`, que es la verdad. Cargar de más afirmaría algo que el anexo no
dice.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from database.models import CompensatoryDuty, FractionNomRequirement

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from ingestion.se.anexo_2_4_1 import FilaNom
    from ingestion.se.cuotas_compensatorias import ParsedCompensatoryDuty

log = structlog.stdlib.get_logger("ingestion.se.load")

#: Vigencia del anexo cargado. El documento es el Acuerdo de Reglas de la SE
#: en su versión del 16-may-2022, que es la que se capturó en RAW.
VIGENCIA: Final[date] = date(2022, 5, 16)

FUENTE: Final[str] = (
    "https://www.snice.gob.mx/~oracle/SNICE_DOCS/"
    "REGLAS-ANEXO241PDF-REGLAS_20220516-20220516.4.1.pdf"
)


def cargar(
    session: Session,
    filas: Sequence[FilaNom],
    *,
    content_hash: str,
    minio_key: str,
) -> int:
    """Escribe las correlaciones que falten. Idempotente.

    `content_hash` es el del PDF capturado, no el de cada fila: lo que se puede
    demostrar es que estas correlaciones salieron de ESE documento. Repetirlo
    en cada fila no es redundancia — es lo que permite, dentro de un año,
    probar de dónde salió una obligación concreta.
    """
    existentes = {
        (f.fraction_code, f.nom_code, f.numeral)
        for f in session.scalars(
            sa.select(FractionNomRequirement).where(FractionNomRequirement.valid_from == VIGENCIA)
        ).all()
    }

    creadas = 0
    for fila in filas:
        clave = (fila.fraction_code, fila.nom_code, fila.numeral)
        if clave in existentes:
            continue
        existentes.add(clave)
        session.add(
            FractionNomRequirement(
                fraction_code=fila.fraction_code,
                nom_code=fila.nom_code,
                numeral=fila.numeral,
                scope_note=fila.scope_note,
                # OFFICIAL: sale del Acuerdo publicado en el DOF, no de
                # nosotros. Lo que es nuestro —y por eso queda fuera de esta
                # tabla— es la interpretación de la acotación.
                data_origin="OFFICIAL",
                valid_from=VIGENCIA,
                published_at=VIGENCIA,
                source_url=FUENTE,
                source_document=f"Anexo 2.4.1 del Acuerdo de Reglas de la SE ({minio_key})",
                content_hash=content_hash,
                retrieved_at=datetime.now(UTC),
            )
        )
        creadas += 1

    session.flush()
    log.info("se.anexo241.cargado", creadas=creadas, recibidas=len(filas))
    return creadas


def cargar_cuotas_compensatorias(
    session: Session,
    filas: Sequence[ParsedCompensatoryDuty],
    *,
    content_hash: str,
    source_url: str,
    source_document: str,
    retrieved_at: datetime | None = None,
) -> int:
    """Escribe las cuotas compensatorias que falten. Idempotente.

    Identidad por `(origin_country, fraction_code, exporter_name,
    valid_from)` — misma `UniqueConstraint` de la tabla. Una fila ya
    cargada no se vuelve a tocar: si una resolución se corrige, cerrar la
    versión anterior a mano es la corrección correcta, no una
    reconciliación automática (mismo criterio que `cargar()`, arriba).
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    existentes = {
        (d.origin_country, d.fraction_code, d.exporter_name, d.valid_from)
        for d in session.scalars(sa.select(CompensatoryDuty)).all()
    }

    creadas = 0
    for fila in filas:
        clave = (fila.origin_country, fila.fraction_code, fila.exporter_name, fila.valid_from)
        if clave in existentes:
            continue
        existentes.add(clave)
        session.add(
            CompensatoryDuty(
                origin_country=fila.origin_country,
                fraction_code=fila.fraction_code,
                exporter_name=fila.exporter_name,
                rate=Decimal(fila.rate),
                rate_currency=fila.rate_currency,
                rate_unit=fila.rate_unit,
                scope_note=fila.scope_note,
                # OFFICIAL: sale de la resolución publicada en el DOF, no
                # de nosotros.
                data_origin="OFFICIAL",
                valid_from=fila.valid_from,
                valid_to=fila.valid_to,
                published_at=fila.valid_from,
                source_url=source_url,
                source_document=source_document,
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )
        creadas += 1

    session.flush()
    log.info("se.cuotas_compensatorias.cargado", creadas=creadas, recibidas=len(filas))
    return creadas
