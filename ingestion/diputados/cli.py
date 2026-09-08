"""CLI de ingesta de la Ley Aduanera: RAW -> PARSED -> VALIDATED -> DATABASE.

Mismo contrato que `ingestion.dof.cli` / `ingestion.snice.cli`: `--target`
obligatorio, mueve base y MinIO juntos, RAW verificado antes de escribir en
la base (regla 7 CLAUDE.md).

Uso:
    python -m ingestion.diputados.cli --target local
    python -m ingestion.diputados.cli --target shared
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from apps.api.config import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.diputados import ley_aduanera, load
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.diputados.cli")

LEY_ADUANERA_KEY = "diputados/ley_aduanera_20251119.pdf"


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
        "--raw-only",
        action="store_true",
        help="Solo sube y verifica el RAW en --target; no toca la base.",
    )
    parser.add_argument(
        "--chunks",
        action="store_true",
        help=(
            "Además de regulatory.legal_rules, carga un chunk por artículo en "
            "regulatory.legal_chunks (§27, RAG) — sin embedding todavía: "
            "recuperable por término, no por similitud, hasta que se vectorice."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = None if args.raw_only else _database_url(args.target)
    minio_target = _minio_target(args.target)

    log.info("diputados.ley_aduanera.cli.start", target=args.target)

    with tempfile.TemporaryDirectory(prefix="ley_aduanera_") as tmp:
        tmp_path = Path(tmp)

        pdf_bytes = raw.fetch(load.LEY_ADUANERA_SOURCE_URL)
        capture = raw.store_raw_bytes(
            pdf_bytes,
            source_url=load.LEY_ADUANERA_SOURCE_URL,
            minio_key=LEY_ADUANERA_KEY,
            target=minio_target,
        )
        pdf_path = tmp_path / "ley_aduanera.pdf"
        pdf_path.write_bytes(pdf_bytes)

        raw.verify_stored(target=minio_target, minio_key=LEY_ADUANERA_KEY)

        if args.raw_only:
            print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
            log.info("diputados.ley_aduanera.cli.done", target=args.target, raw_only=True)
            return 0

        lines = ley_aduanera.extract_text(str(pdf_path))
        articulos = ley_aduanera.parse_articles(lines)

    print(f"Parseado: {len(articulos)} artículos de la Ley Aduanera.")

    assert database_url is not None  # solo llegamos aquí sin --raw-only
    engine = create_engine(database_url)
    with Session(engine) as session:
        n_articulos = load.load_ley_aduanera(
            session,
            articulos=articulos,
            content_hash=capture.content_hash,
            retrieved_at=capture.retrieved_at,
        )
        n_chunks = None
        if args.chunks:
            n_chunks = load.load_ley_aduanera_chunks(
                session,
                articulos=articulos,
                content_hash=capture.content_hash,
                retrieved_at=capture.retrieved_at,
            )
        session.commit()

    print(f"OK ({args.target}): {n_articulos} artículos insertados en regulatory.legal_rules.")
    if n_chunks is not None:
        print(f"OK ({args.target}): {n_chunks} chunks insertados en regulatory.legal_chunks.")
    log.info(
        "diputados.ley_aduanera.cli.done",
        target=args.target,
        articulos=n_articulos,
        chunks=n_chunks,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
