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
from database.models import (
    CompensatoryDuty,
    CompensatoryDutyListing,
    FractionNomRequirement,
    ProsecRate,
    Regla8aFraction,
    TariffFraction,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from ingestion.se.anexo_2_4_1 import FilaNom
    from ingestion.se.anexo_2_5_1 import ParsedListing
    from ingestion.se.cuotas_compensatorias import ParsedCompensatoryDuty
    from ingestion.se.prosec import FilaProsec
    from ingestion.se.regla_8a import FraccionRegla8a

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
                published_at=fila.published_at,
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


def cargar_prosec(
    session: Session,
    filas: Sequence[FilaProsec],
    *,
    content_hash: str,
    minio_key: str,
    retrieved_at: datetime | None = None,
) -> tuple[int, list[str]]:
    """Escribe las tasas del artículo 5 del Decreto PROSEC (ADR 0011). Idempotente.

    Una fila cuya fracción no esté vigente en la LIGIE cargada en la fecha de
    inicio de vigencia NO se carga: sería una tasa para una fracción que no
    existe ese día (NEEDS_VALIDATION). Devuelve `(creadas, omitidas)`.
    """
    from ingestion.se import prosec

    retrieved_at = retrieved_at or datetime.now(UTC)
    vigentes = set(
        session.scalars(
            sa.select(TariffFraction.code).where(
                TariffFraction.valid_from <= prosec.VALID_FROM,
                sa.or_(
                    TariffFraction.valid_to.is_(None),
                    TariffFraction.valid_to >= prosec.VALID_FROM,
                ),
            )
        )
    )
    existentes = set(
        session.execute(
            sa.select(
                ProsecRate.sector_code,
                ProsecRate.fraction_code,
                ProsecRate.scope_note,
                ProsecRate.valid_from,
            )
        ).tuples()
    )
    # CONTRADICCIONES DEL PROPIO DECRETO (20-oct)
    #
    # La misma fracción, en el mismo sector y con la misma acotación, con dos
    # tasas distintas: el sector XV lista la 7419.80.02 al 5 % y exenta. No se
    # elige ninguna —sería inventar cuál rige— y, si una ya se cargó, se
    # retira: `NEEDS_VALIDATION`.
    tasas: dict[tuple[str, str, str | None], set[Decimal]] = {}
    for fila in filas:
        tasas.setdefault((fila.sector_code, fila.fraction_code, fila.acotacion), set()).add(
            fila.igi_rate
        )
    contradictorias = {clave for clave, valores in tasas.items() if len(valores) > 1}
    for sector, fraccion, acotacion in contradictorias:
        session.execute(
            sa.delete(ProsecRate).where(
                ProsecRate.sector_code == sector,
                ProsecRate.fraction_code == fraccion,
                ProsecRate.scope_note.is_not_distinct_from(acotacion),
                ProsecRate.valid_from == prosec.VALID_FROM,
                ProsecRate.source_url == prosec.SOURCE_URL,
            )
        )
        existentes.discard((sector, fraccion, acotacion, prosec.VALID_FROM))

    creadas = 0
    omitidas: list[str] = [
        f"{sector} {fraccion}: el decreto le da {len(tasas[(sector, fraccion, acotacion)])} "
        "tasas distintas con la misma acotación (NEEDS_VALIDATION)"
        for sector, fraccion, acotacion in sorted(
            contradictorias, key=lambda c: (c[0], c[1], c[2] or "")
        )
    ]
    for fila in filas:
        if (fila.sector_code, fila.fraction_code, fila.acotacion) in contradictorias:
            continue
        if fila.fraction_code not in vigentes:
            omitidas.append(
                f"{fila.sector_code} {fila.fraction_code}: no está vigente en la LIGIE el "
                f"{prosec.VALID_FROM} (NEEDS_VALIDATION)"
            )
            continue
        clave = (fila.sector_code, fila.fraction_code, fila.acotacion, prosec.VALID_FROM)
        if clave in existentes:
            continue
        existentes.add(clave)
        session.add(
            ProsecRate(
                sector_code=fila.sector_code,
                sector_name=fila.sector_name,
                fraction_code=fila.fraction_code,
                igi_rate=fila.igi_rate,
                is_partial=fila.is_partial,
                scope_note=fila.acotacion,
                data_origin="OFFICIAL",
                valid_from=prosec.VALID_FROM,
                published_at=prosec.PUBLISHED_AT,
                source_url=prosec.SOURCE_URL,
                source_document=f"{prosec.SOURCE_DOCUMENT} ({minio_key})",
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )
        creadas += 1
    session.flush()
    log.info("se.prosec.cargado", creadas=creadas, recibidas=len(filas), omitidas=len(omitidas))
    return creadas, omitidas


def cargar_regla_8a(
    session: Session,
    fracciones: Sequence[FraccionRegla8a],
    *,
    retrieved_at: datetime | None = None,
) -> int:
    """Escribe qué 9802 corresponde a cada sector (ADR 0011). Idempotente.

    La fuente de cada fila es la propia 9802 en la LIGIE —su texto es el que
    nombra el programa sectorial—, así que se copian su URL, su documento, su
    hash y su vigencia. La tasa NO se copia: se lee de la LIGIE al consumir.
    """
    retrieved_at = retrieved_at or datetime.now(UTC)
    ligie = {
        f.code: f
        for f in session.scalars(
            sa.select(TariffFraction).where(
                TariffFraction.code.in_([x.fraction_code for x in fracciones]),
                TariffFraction.valid_to.is_(None),
            )
        )
    }
    existentes = set(
        session.execute(
            sa.select(
                Regla8aFraction.sector_code,
                Regla8aFraction.fraction_code,
                Regla8aFraction.valid_from,
            )
        ).tuples()
    )
    creadas = 0
    for fr in fracciones:
        origen = ligie.get(fr.fraction_code)
        if origen is None:
            continue
        clave = (fr.sector_code, fr.fraction_code, origen.valid_from)
        if clave in existentes:
            continue
        existentes.add(clave)
        session.add(
            Regla8aFraction(
                sector_code=fr.sector_code,
                sector_name=fr.sector_name,
                fraction_code=fr.fraction_code,
                scope_note=fr.scope_note,
                data_origin="OFFICIAL",
                source_id=origen.source_id,
                valid_from=origen.valid_from,
                published_at=origen.published_at,
                source_url=origen.source_url,
                source_document=origen.source_document,
                content_hash=origen.content_hash,
                retrieved_at=retrieved_at,
            )
        )
        creadas += 1
    session.flush()
    log.info("se.regla_8a.cargado", creadas=creadas, recibidas=len(fracciones))
    return creadas


def cargar_anexo_2_5_1(
    session: Session,
    filas: Sequence[ParsedListing],
    *,
    content_hash: str,
    minio_key: str,
    retrieved_at: datetime | None = None,
) -> tuple[int, list[str]]:
    """Escribe el índice del Anexo 2.5.1 (ADR 0017). Idempotente por la clave
    natural.

    Una fila cuya fracción no esté en la LIGIE vigente el día en que el anexo
    entra en vigor no se carga: `NEEDS_VALIDATION`. Devuelve `(creadas,
    omitidas)`.
    """
    from ingestion.se import anexo_2_5_1

    retrieved_at = retrieved_at or datetime.now(UTC)
    desde = anexo_2_5_1.VALID_FROM
    vigentes = set(
        session.scalars(
            sa.select(TariffFraction.code).where(
                TariffFraction.valid_from <= desde,
                sa.or_(TariffFraction.valid_to.is_(None), TariffFraction.valid_to >= desde),
            )
        )
    )
    existentes = set(
        session.execute(
            sa.select(
                CompensatoryDutyListing.fraction_code,
                CompensatoryDutyListing.origin_country,
                CompensatoryDutyListing.product_description,
                CompensatoryDutyListing.exporter_text,
                CompensatoryDutyListing.first_resolution_date,
            ).where(CompensatoryDutyListing.valid_from == desde)
        ).tuples()
    )
    creadas = 0
    omitidas: list[str] = []
    for fila in filas:
        if fila.fraction_code not in vigentes:
            omitidas.append(
                f"{fila.fraction_code} {fila.origin_country}: no está vigente en la LIGIE el "
                f"{desde} (NEEDS_VALIDATION)"
            )
            continue
        clave = (
            fila.fraction_code,
            fila.origin_country,
            fila.product_description,
            fila.exporter_text,
            fila.first_resolution_date,
        )
        if clave in existentes:
            continue
        existentes.add(clave)
        session.add(
            CompensatoryDutyListing(
                product_description=fila.product_description,
                fraction_code=fila.fraction_code,
                origin_country=fila.origin_country,
                exporter_text=fila.exporter_text,
                applies_to_all_others=fila.applies_to_all_others,
                duty_text=fila.duty_text,
                scope_note=fila.scope_note,
                resolution_history=[
                    {"tipo": r.tipo, "fecha": r.fecha.isoformat()} for r in fila.resolution_history
                ],
                first_resolution_date=fila.first_resolution_date,
                latest_resolution_date=fila.latest_resolution_date,
                data_origin="OFFICIAL",
                valid_from=desde,
                published_at=anexo_2_5_1.PUBLISHED_AT,
                source_url=anexo_2_5_1.SOURCE_URL,
                source_document=f"{anexo_2_5_1.SOURCE_DOCUMENT} ({minio_key})",
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )
        creadas += 1
    session.flush()
    log.info(
        "se.anexo_2_5_1.cargado", creadas=creadas, recibidas=len(filas), omitidas=len(omitidas)
    )
    return creadas, omitidas
