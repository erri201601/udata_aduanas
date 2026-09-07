"""CLI de ingesta SNICE: RAW -> PARSED -> NORMALIZED -> VALIDATED -> DATABASE.

El destino (`local` / `shared`) es un argumento obligatorio, nunca un default
silencioso: escribir en la base compartida del equipo debe ser una decisión
visible en la línea de comandos, no algo que pasa porque una variable de
entorno estaba puesta (Persona 1, 2026-09-07).

Uso:
    python -m ingestion.snice.cli --target local  --chapters 84 85
    python -m ingestion.snice.cli --target shared --chapters 84 85

`--target local` usa `DATABASE_URL`/`POSTGRES_*` de tu `.env` (siempre tu
Postgres local). `--target shared` exige `ADUANERO_SHARED_URL` en el entorno
— nunca la escribas aquí ni la pegues en un chat; ponla en tu `.env` cuando
Persona 1 te dé la contraseña por canal seguro.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import structlog
from apps.api.config import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.snice import load, nico, raw, tariff

log = structlog.stdlib.get_logger("ingestion.snice.cli")

TARIFA_URL = (
    "https://www.snice.gob.mx/~oracle/SNICE_DOCS/"
    "FRACCIONESARANCELARIAS-LIGIE_20260420-20260420.xlsx"
)
NICO_URL = "https://www.snice.gob.mx/~oracle/SNICE_DOCS/NICO-ABRIL24-LIGIE_20240415-20240415.XLSX"
LIGIE_PDF_URL = (
    "https://www.snice.gob.mx/~oracle/SNICE_DOCS/LIGIE-UNIFICADA-LIGIE_20250728-20250728.pdf"
)


def _database_url(target: str) -> str:
    """El destino nunca tiene default: `local` o `shared`, siempre explícito."""
    if target == "shared":
        url = os.environ.get("ADUANERO_SHARED_URL")
        if not url:
            raise SystemExit(
                "ADUANERO_SHARED_URL no está definida. Pide la contraseña a Persona 1 "
                "por canal seguro y ponla en tu .env — nunca en un chat ni aquí."
            )
        return url
    return get_settings().sqlalchemy_url


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        required=True,
        choices=["local", "shared"],
        help="'shared' escribe en la base del equipo — decisión explícita, sin default.",
    )
    parser.add_argument(
        "--chapters",
        required=True,
        nargs="+",
        metavar="NN",
        help="Capítulos de 2 dígitos a cargar, p. ej. --chapters 84 85",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    chapters = frozenset(args.chapters)
    database_url = _database_url(args.target)

    log.info("snice.cli.start", target=args.target, chapters=sorted(chapters))

    with tempfile.TemporaryDirectory(prefix="snice_") as tmp:
        tmp_path = Path(tmp)

        tarifa_bytes = raw.fetch(TARIFA_URL)
        tarifa_capture = raw.store_raw_bytes(
            tarifa_bytes, source_url=TARIFA_URL, minio_key="snice/fracciones_20260420.xlsx"
        )
        tarifa_path = tmp_path / "fracciones.xlsx"
        tarifa_path.write_bytes(tarifa_bytes)

        nico_bytes = raw.fetch(NICO_URL)
        nico_capture = raw.store_raw_bytes(
            nico_bytes, source_url=NICO_URL, minio_key="snice/nico_20240415.xlsx"
        )
        nico_path = tmp_path / "nico.xlsx"
        nico_path.write_bytes(nico_bytes)

        ligie_bytes = raw.fetch(LIGIE_PDF_URL)
        ligie_capture = raw.store_raw_bytes(
            ligie_bytes,
            source_url=LIGIE_PDF_URL,
            minio_key="snice/ligie_unificada_20250728.pdf",
        )

        fa_result = tariff.parse_fracciones(
            tariff.iter_fraccion_rows(tarifa_path),
            chapters,
            source_url=tarifa_capture.source_url,
            content_hash=tarifa_capture.content_hash,
            retrieved_at=tarifa_capture.retrieved_at,
        )
        nico_result = nico.parse_nicos(
            nico.iter_nico_rows_from_standalone(nico_path),
            chapters,
            source_url=nico_capture.source_url,
            content_hash=nico_capture.content_hash,
            retrieved_at=nico_capture.retrieved_at,
        )

    print(
        f"Reconciliación tarifa: {fa_result.reconciliation(declared_by_source=len(fa_result.accepted) + len(fa_result.rejected))}"
    )
    print(
        f"Reconciliación NICO:   {nico_result.reconciliation(declared_by_source=len(nico_result.accepted) + len(nico_result.rejected))}"
    )
    if fa_result.rate_warnings:
        print(f"Advertencias de tasa: {len(fa_result.rate_warnings)}")

    engine = create_engine(database_url)
    with Session(engine) as session:
        n_fracciones, n_nicos = load.load_chapters(
            session,
            fracciones=fa_result.accepted,
            nicos=nico_result.accepted,
            ligie_content_hash=ligie_capture.content_hash,
        )
        session.commit()

    print(f"OK ({args.target}): {n_fracciones} fracciones, {n_nicos} NICO insertados.")
    log.info("snice.cli.done", target=args.target, fracciones=n_fracciones, nicos=n_nicos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
