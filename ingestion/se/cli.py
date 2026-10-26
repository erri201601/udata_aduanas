"""CLI de ingesta de cuotas compensatorias (SE): RAW -> PARSED -> DATABASE.

Mismo contrato que `ingestion.banxico.cli`/`ingestion.dof.cli`: `--target` es
obligatorio y mueve AMBOS destinos (base y MinIO) juntos; el RAW se verifica
en el destino antes de escribir una sola fila (regla 7 CLAUDE.md).

A diferencia de esos dos, aquí NO hay un documento único que crezca o un
catálogo que se recargue completo: cada cuota compensatoria es SU PROPIA
resolución del DOF (ver `ingestion.se.cuotas_compensatorias`), así que cada
una tiene su propio flag: `--cable-acero-china` (ADR 0009) y, desde el
26-oct, `--cuotas-26-oct` con las ollas de presión de China y la tubería de
la India (ADR 0027). Las demás combinaciones del corpus no tienen cuota
vigente en agosto de 2026, y el ADR 0027 dice por qué con su fuente.

`--anexo-2-5-1` carga el índice del Anexo 2.5.1 (DOF 25-nov-2022): dónde hay
cuota, con el texto tal cual y sin importe (ADR 0017).

También el Decreto PROSEC (`--prosec`, artículo 5) y la Regla 8ª
(`--regla-8a`, desde las 9802 de la LIGIE ya cargada), ADR 0011.

Uso:
    python -m ingestion.se.cli --target local  --prosec
    python -m ingestion.se.cli --target local  --regla-8a
    python -m ingestion.se.cli --target local  --cable-acero-china
    python -m ingestion.se.cli --target local  --anexo-2-5-1
    python -m ingestion.se.cli --target local  --anexo-2-4-1
    python -m ingestion.se.cli --target shared --cable-acero-china --raw-only
"""

from __future__ import annotations

import argparse
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from apps.api.logging import con_corrida
from database.models import ProsecRate, TariffFraction
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.se import anexo_2_4_1, anexo_2_5_1, cuotas_compensatorias, load, prosec, regla_8a
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.se.cli")

CABLE_ACERO_CHINA_MINIO_KEY = "se/cuota_compensatoria_cable_acero_china_ec32-24.html"
PROSEC_MINIO_KEY = "se/decreto_prosec_20240826.pdf"
#: Una por resolución, con su fecha de DOF: cada cuota es un documento propio.
CUOTAS_26_OCT: tuple[tuple[str, str, str, str], ...] = (
    (
        "ollas_de_presion_china",
        "se/cuota_compensatoria_ollas_presion_china_20260306.html",
        "OLLAS_PRESION_CHINA_SOURCE_URL",
        "OLLAS_PRESION_CHINA_SOURCE_DOCUMENT",
    ),
    (
        "tuberia_india",
        "se/cuota_compensatoria_tuberia_india_20221003.html",
        "TUBERIA_INDIA_SOURCE_URL",
        "TUBERIA_INDIA_SOURCE_DOCUMENT",
    ),
)


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
        "--anexo-2-4-1",
        action="store_true",
        help=(
            "Anexo 2.4.1 (NOM) en su versión del DOF 25-nov-2022, vigente desde el "
            "12-dic-2022; cierra la versión anterior."
        ),
    )
    parser.add_argument(
        "--anexo-2-5-1",
        action="store_true",
        help="Anexo 2.5.1: dónde hay cuota compensatoria, como índice y sin importe (ADR 0017).",
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
        "--cuotas-26-oct",
        action="store_true",
        help="Ollas de presión de China y tubería de la India, verificadas el 26-oct (ADR 0027).",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Solo sube y verifica el RAW en --target; no toca la base.",
    )
    return parser.parse_args(argv)


@con_corrida("ingestion.se")
def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.prosec:
        return _prosec(args)
    if args.anexo_2_5_1:
        return _anexo_2_5_1(args)
    if args.anexo_2_4_1:
        return _anexo_2_4_1(args)
    if args.regla_8a:
        return _regla_8a(args)
    if args.cuotas_26_oct:
        return _cuotas_26_oct(args)
    if not args.raw_only and not args.cable_acero_china:
        raise SystemExit(
            "--cable-acero-china, --prosec, --anexo-2-4-1, --anexo-2-5-1 o --regla-8a "
            "es obligatorio "
            "salvo con --raw-only"
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


def _cuotas_26_oct(args: argparse.Namespace) -> int:
    """RAW → PARSED → DATABASE de cada resolución, una por una (ADR 0027)."""
    database_url = None if args.raw_only else _database_url(args.target)
    minio_target = _minio_target(args.target)
    total = 0
    for funcion, minio_key, url_attr, doc_attr in CUOTAS_26_OCT:
        url = getattr(cuotas_compensatorias, url_attr)
        capture = raw.store_raw_bytes(
            raw.fetch(url), source_url=url, minio_key=minio_key, target=minio_target
        )
        raw.verify_stored(target=minio_target, minio_key=minio_key)
        if args.raw_only:
            print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
            continue
        filas = getattr(cuotas_compensatorias, funcion)()
        assert database_url is not None
        with Session(create_engine(database_url)) as session:
            n = load.cargar_cuotas_compensatorias(
                session,
                filas,
                content_hash=capture.content_hash,
                source_url=url,
                source_document=getattr(cuotas_compensatorias, doc_attr),
                retrieved_at=capture.retrieved_at,
            )
            session.commit()
        total += n
        print(f"{funcion}: {n} filas insertadas (de {len(filas)} leídas).")
    log.info("se.cli.done", target=args.target, cuotas_26_oct=total)
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


def _anexo_2_5_1(args: argparse.Namespace) -> int:
    """RAW → PARSED → DATABASE del Anexo 2.5.1 (ADR 0017).

    El HTML del DOF cambia entre descargas (la barra lateral trae el tipo de
    cambio del día), así que la clave de MinIO lleva el hash: cada captura es
    un objeto propio y el `content_hash` de cada fila apunta al suyo (#265).
    """
    from apps.api.logging import registrar

    minio_target = _minio_target(args.target)
    datos = raw.fetch(anexo_2_5_1.SOURCE_URL)
    clave = f"se/anexo_2_5_1_20221125_{raw.content_hash(datos)[:16]}.html"
    capture = raw.store_raw_bytes(
        datos, source_url=anexo_2_5_1.SOURCE_URL, minio_key=clave, target=minio_target
    )
    raw.verify_stored(target=minio_target, minio_key=clave)
    if args.raw_only:
        print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
        return 0

    filas = anexo_2_5_1.parse(datos.decode("utf-8"))
    print(
        f"Parseado: {len(filas)} filas del Anexo 2.5.1 — "
        f"{len({f.product_description for f in filas})} productos, "
        f"{len({f.fraction_code for f in filas})} fracciones, "
        f"{len({f.origin_country for f in filas})} orígenes."
    )
    engine = create_engine(_database_url(args.target))
    with Session(engine) as session:
        creadas, omitidas = load.cargar_anexo_2_5_1(
            session,
            filas,
            content_hash=capture.content_hash,
            minio_key=clave,
            retrieved_at=capture.retrieved_at,
        )
        session.commit()
    for motivo in omitidas:
        print(f"NO SE CARGA: {motivo}")
    registrar(records=creadas, errors=len(omitidas))
    print(f"OK ({args.target}): {creadas} filas del Anexo 2.5.1 insertadas.")
    log.info("se.anexo_2_5_1.cli.done", target=args.target, creadas=creadas, omitidas=len(omitidas))
    return 0


def _anexo_2_4_1(args: argparse.Namespace) -> int:
    """RAW → PARSED → DATABASE del Anexo 2.4.1, versión DOF 25-nov-2022.

    Es la misma nota del DOF que el 2.5.1: el acuerdo reforma los dos anexos.
    """
    from apps.api.logging import registrar

    minio_target = _minio_target(args.target)
    datos = raw.fetch(load.FUENTE_2022_11)
    clave = f"se/anexo_2_4_1_20221125_{raw.content_hash(datos)[:16]}.html"
    capture = raw.store_raw_bytes(
        datos, source_url=load.FUENTE_2022_11, minio_key=clave, target=minio_target
    )
    raw.verify_stored(target=minio_target, minio_key=clave)
    if args.raw_only:
        print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
        return 0

    filas = anexo_2_4_1.parse_html(datos.decode("utf-8"))
    print(
        f"Parseado: {len(filas)} correlaciones fracción → NOM — "
        f"{len({f.fraction_code for f in filas})} fracciones, "
        f"{len({f.nom_code for f in filas})} NOM."
    )
    engine = create_engine(_database_url(args.target))
    with Session(engine) as session:
        creadas, cerradas, omitidas = load.cargar_version_2022_11(
            session,
            filas,
            content_hash=capture.content_hash,
            minio_key=clave,
            retrieved_at=capture.retrieved_at,
        )
        session.commit()
    for motivo in omitidas:
        print(f"NO SE CARGA: {motivo}")
    registrar(records=creadas, errors=len(omitidas), cerradas=cerradas)
    print(
        f"OK ({args.target}): {creadas} correlaciones insertadas; "
        f"{cerradas} de la versión anterior cerradas al "
        f"{load.VIGENCIA_2022_11 - timedelta(days=1)}."
    )
    return 0


def _regla_8a(args: argparse.Namespace) -> int:
    """Las 9802 de la LIGIE cargada → su sector PROSEC (sin descarga: el texto
    oficial ya está en `tariff_fractions`)."""
    engine = create_engine(_database_url(args.target))
    with Session(engine) as session:
        sectores = dict(
            session.execute(sa.select(ProsecRate.sector_code, ProsecRate.sector_name).distinct())
            .tuples()
            .all()
        )
        if not sectores:
            raise SystemExit("No hay sectores PROSEC cargados: corre antes --prosec.")
        nueve_ocho = [
            (codigo, texto)
            for codigo, texto in session.execute(
                sa.select(TariffFraction.code, TariffFraction.description).where(
                    TariffFraction.code.like("9802%"), TariffFraction.valid_to.is_(None)
                )
            ).all()
        ]
        fracciones, sin_sector = regla_8a.fracciones_regla_8a(nueve_ocho, sectores)
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
