"""CLI de ingesta del tipo de cambio FIX (USD/MXN): RAW -> PARSED -> DATABASE.

Mismo contrato que `ingestion.snice.cli`/`ingestion.dof.cli`: `--target` es
obligatorio y mueve AMBOS destinos (base y MinIO) juntos; el RAW se verifica
en el destino antes de escribir una sola fila (regla 7 CLAUDE.md).

Es una serie que CRECE todos los días hábiles, no un catálogo que se carga
una sola vez -- por default se piden los últimos 7 días (`--start`/`--end`
para un rango explícito, p. ej. una carga inicial de varios meses).

Uso:
    python -m ingestion.banxico.cli --target local
    python -m ingestion.banxico.cli --target local  --start 2026-01-01 --end 2026-10-06
    python -m ingestion.banxico.cli --target shared --raw-only
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from typing import TYPE_CHECKING

import structlog
from apps.api.config import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.banxico import fix, load
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.banxico.cli")

MINIO_KEY_TEMPLATE = "banxico/fix_{start}_{end}.html"


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
        "--start",
        type=date.fromisoformat,
        default=None,
        help="YYYY-MM-DD. Por default, 7 días atrás.",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="YYYY-MM-DD. Por default, hoy.",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Solo sube y verifica el RAW en --target; no toca la base.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    end = args.end or date.today()
    start = args.start or (end - timedelta(days=7))
    if start > end:
        raise SystemExit(f"--start ({start}) no puede ser posterior a --end ({end})")

    database_url = None if args.raw_only else _database_url(args.target)
    minio_target = _minio_target(args.target)

    log.info("banxico.cli.start", target=args.target, start=str(start), end=str(end))

    url = fix.fix_url(start=start, end=end)
    html_bytes = raw.fetch(url)
    minio_key = MINIO_KEY_TEMPLATE.format(start=start.isoformat(), end=end.isoformat())
    capture = raw.store_raw_bytes(
        html_bytes, source_url=url, minio_key=minio_key, target=minio_target
    )
    raw.verify_stored(target=minio_target, minio_key=minio_key)

    if args.raw_only:
        print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
        log.info("banxico.cli.done", target=args.target, raw_only=True)
        return 0

    parsed = fix.parse_fix_html(html_bytes.decode("utf-8"))
    print(f"Parseado: {len(parsed)} valores del FIX entre {start} y {end}.")

    assert database_url is not None  # solo llegamos aquí sin --raw-only
    engine = create_engine(database_url)
    with Session(engine) as session:
        n_insertadas = load.load_exchange_rates(
            session, rates=parsed, content_hash=capture.content_hash
        )
        session.commit()
    print(
        f"OK ({args.target}): {n_insertadas} valores del FIX insertados (de {len(parsed)} leídos)."
    )
    log.info("banxico.cli.done", target=args.target, parseadas=len(parsed), insertadas=n_insertadas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
