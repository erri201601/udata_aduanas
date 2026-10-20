"""CLI de ingesta de cuotas compensatorias (SE): RAW -> PARSED -> DATABASE.

Mismo contrato que `ingestion.banxico.cli`/`ingestion.dof.cli`: `--target` es
obligatorio y mueve AMBOS destinos (base y MinIO) juntos; el RAW se verifica
en el destino antes de escribir una sola fila (regla 7 CLAUDE.md).

A diferencia de esos dos, aquí NO hay un documento único que crezca o un
catálogo que se recargue completo: cada cuota compensatoria es SU PROPIA
resolución del DOF (ver `ingestion.se.cuotas_compensatorias`), así que cada
una tiene su propio flag. Por ahora sólo existe una: `--cable-acero-china`
(ADR 0009). Las demás combinaciones del reconocimiento
(`docs/RECONOCIMIENTO_CUOTAS_COMPENSATORIAS.md`) no tienen flag todavía
porque no tienen resolución primaria verificada.

También el Decreto PROSEC (`--prosec`, artículo 5) y la Regla 8ª
(`--regla-8a`, desde las 9802 de la LIGIE ya cargada), ADR 0011.

Uso:
    python -m ingestion.se.cli --target local  --prosec
    python -m ingestion.se.cli --target local  --regla-8a
    python -m ingestion.se.cli --target local  --cable-acero-china
    python -m ingestion.se.cli --target shared --cable-acero-china --raw-only
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from database.models import ProsecRate, TariffFraction
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.se import cuotas_compensatorias, load, prosec, regla_8a
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.se.cli")

CABLE_ACERO_CHINA_MINIO_KEY = "se/cuota_compensatoria_cable_acero_china_ec32-24.html"
PROSEC_MINIO_KEY = "se/decreto_prosec_20240826.pdf"


def _database_url(target: str) -> str:
    if target == "shared":
        url = os.environ.get("ADUANERO_SHARED_URL")
        if not url:
            raise SystemExit(
                "ADUANERO_SHARED_URL no está definida. Pide la contraseña a Persona 1 "
                "por canal seguro y ponla en tu .env — nunca en un chat ni aquí."
            )
        return url
    return get_settings().sqlalchemy_url


def _minio_target(target: str) -> MinioTarget:
    if target == "shared":
        return raw.shared_target()
    return raw.local_target()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        required=True,
        choices=["local", "shared"],
        help="'shared' escribe en la base y el MinIO del equipo — decisión explícita.",
    )
    parser.add_argument(
        "--cable-acero-china",
        action="store_true",
        help=(
            "Cuota compensatoria a cables de acero originarios de China "
            "(expediente EC 32-24, DOF 2026-04-09) -- ADR 0009."
        ),
    )
    parser.add_argument(
        "--prosec",
        action="store_true",
        help="Decreto PROSEC, artículo 5: tasas por sector y fracción (ADR 0011).",
    )
    parser.add_argument(
        "--regla-8a",
        action="store_true",
        help=(
            "Regla 8ª: qué 9802 corresponde a cada sector, leído de la LIGIE ya "
            "cargada. Requiere --prosec cargado antes (los nombres de sector)."
        ),
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Solo sube y verifica el RAW en --target; no toca la base.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.prosec:
        return _prosec(args)
    if args.regla_8a:
        return _regla_8a(args)
    if not args.raw_only and not args.cable_acero_china:
        raise SystemExit(
            "--cable-acero-china, --prosec o --regla-8a es obligatorio salvo con --raw-only"
        )

    database_url = None if args.raw_only else _database_url(args.target)
    minio_target = _minio_target(args.target)

    log.info("se.cli.start", target=args.target)

    url = cuotas_compensatorias.CABLE_ACERO_CHINA_SOURCE_URL
    html_bytes = raw.fetch(url)
    capture = raw.store_raw_bytes(
        html_bytes, source_url=url, minio_key=CABLE_ACERO_CHINA_MINIO_KEY, target=minio_target
    )
    raw.verify_stored(target=minio_target, minio_key=CABLE_ACERO_CHINA_MINIO_KEY)

    if args.raw_only:
        print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
        log.info("se.cli.done", target=args.target, raw_only=True)
        return 0

    filas = cuotas_compensatorias.cable_de_acero_china()
    print(f"Parseado: {len(filas)} fracciones de la cuota compensatoria (cable de acero, China).")

    assert database_url is not None  # solo llegamos aquí sin --raw-only
    engine = create_engine(database_url)
    with Session(engine) as session:
        n_insertadas = load.cargar_cuotas_compensatorias(
            session,
            filas,
            content_hash=capture.content_hash,
            source_url=url,
            source_document=cuotas_compensatorias.CABLE_ACERO_CHINA_SOURCE_DOCUMENT,
            retrieved_at=capture.retrieved_at,
        )
        session.commit()
    print(
        f"OK ({args.target}): {n_insertadas} cuotas compensatorias insertadas (de {len(filas)} leídas)."
    )
    log.info("se.cli.done", target=args.target, parseadas=len(filas), insertadas=n_insertadas)
    return 0


def _prosec(args: argparse.Namespace) -> int:
    """RAW → PARSED → DATABASE del artículo 5 del Decreto PROSEC."""
    minio_target = _minio_target(args.target)
    pdf_bytes = raw.fetch(prosec.SOURCE_URL)
    capture = raw.store_raw_bytes(
        pdf_bytes, source_url=prosec.SOURCE_URL, minio_key=PROSEC_MINIO_KEY, target=minio_target
    )
    raw.verify_stored(target=minio_target, minio_key=PROSEC_MINIO_KEY)
    if args.raw_only:
        print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
        return 0

    with tempfile.TemporaryDirectory(prefix="prosec_") as tmp:
        ruta = Path(tmp) / "prosec.pdf"
        ruta.write_bytes(pdf_bytes)
        filas = prosec.parse_prosec(str(ruta))
    print(
        f"Parseado: {len(filas)} tasas del artículo 5 en "
        f"{len({f.sector_code for f in filas})} sectores "
        f"({sum(f.is_partial for f in filas)} con acotación)."
    )
    engine = create_engine(_database_url(args.target))
    with Session(engine) as session:
        creadas, omitidas = load.cargar_prosec(
            session,
            filas,
            content_hash=capture.content_hash,
            minio_key=PROSEC_MINIO_KEY,
            retrieved_at=capture.retrieved_at,
        )
        session.commit()
    for motivo in omitidas:
        print(f"NO SE CARGA: {motivo}")
    print(f"OK ({args.target}): {creadas} tasas PROSEC insertadas.")
    log.info("se.prosec.cli.done", target=args.target, creadas=creadas, omitidas=len(omitidas))
    return 0


def _regla_8a(args: argparse.Namespace) -> int:
    """Las 9802 de la LIGIE cargada → su sector PROSEC (sin descarga: el texto
    oficial ya está en `tariff_fractions`)."""
    engine = create_engine(_database_url(args.target))
    with Session(engine) as session:
        sectores = dict(
            session.execute(
                sa.select(ProsecRate.sector_code, ProsecRate.sector_name).distinct()
            ).tuples()
        )
        if not sectores:
            raise SystemExit("No hay sectores PROSEC cargados: corre antes --prosec.")
        nueve_ocho = session.execute(
            sa.select(TariffFraction.code, TariffFraction.description).where(
                TariffFraction.code.like("9802%"), TariffFraction.valid_to.is_(None)
            )
        ).tuples()
        fracciones, sin_sector = regla_8a.fracciones_regla_8a(list(nueve_ocho), sectores)
        creadas = load.cargar_regla_8a(session, fracciones)
        session.commit()
    for motivo in sin_sector:
        print(f"SIN SECTOR: {motivo}")
    print(
        f"OK ({args.target}): {creadas} fracciones de la Regla 8ª insertadas "
        f"({len(fracciones)} con sector, {len(sin_sector)} sin)."
    )
    log.info(
        "se.regla_8a.cli.done", target=args.target, creadas=creadas, sin_sector=len(sin_sector)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
