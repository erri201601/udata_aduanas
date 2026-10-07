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

Uso:
    python -m ingestion.se.cli --target local  --cable-acero-china
    python -m ingestion.se.cli --target shared --cable-acero-china --raw-only
"""

from __future__ import annotations

import argparse
import os
from typing import TYPE_CHECKING

import structlog
from apps.api.config import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.se import cuotas_compensatorias, load
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.se.cli")

CABLE_ACERO_CHINA_MINIO_KEY = "se/cuota_compensatoria_cable_acero_china_ec32-24.html"


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
        "--raw-only",
        action="store_true",
        help="Solo sube y verifica el RAW en --target; no toca la base.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.raw_only and not args.cable_acero_china:
        raise SystemExit("--cable-acero-china es obligatorio salvo con --raw-only")

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


if __name__ == "__main__":
    raise SystemExit(main())
