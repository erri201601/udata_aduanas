"""CLI de ingesta de Diputados: RAW -> PARSED -> VALIDATED -> DATABASE.

Mismo contrato que `ingestion.dof.cli` / `ingestion.snice.cli`: `--target`
obligatorio, mueve base y MinIO juntos, RAW verificado antes de escribir en
la base (regla 7 CLAUDE.md). Ambos RAW (Ley Aduanera y LIGIE) se suben
siempre, se pida o no su carga -- igual que `ingestion.snice.cli` sube los
tres RAW (tarifa, NICO, LIGIE) sin importar qué flag de contenido se pida.

Uso:
    python -m ingestion.diputados.cli --target local  --ley-aduanera
    python -m ingestion.diputados.cli --target local  --ligie
    python -m ingestion.diputados.cli --target shared --ley-aduanera --ligie
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

from ingestion.diputados import ley_aduanera, ligie, load
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.diputados.cli")

LEY_ADUANERA_KEY = "diputados/ley_aduanera_20251119.pdf"
LIGIE_ARTICULO1_KEY = "diputados/ligie_2022_texto_vigente.pdf"


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
        "--ley-aduanera",
        action="store_true",
        help="Carga los 274 artículos de la Ley Aduanera a regulatory.legal_rules.",
    )
    parser.add_argument(
        "--ligie",
        action="store_true",
        help=(
            "Carga el preámbulo y el Artículo 1o. de la LIGIE 2022 a "
            "regulatory.legal_rules -- no la tarifa completa, que ya se carga de "
            "ingestion.snice.tariff_headings."
        ),
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
            "Con --ley-aduanera, además carga un chunk por artículo en "
            "regulatory.legal_chunks (§27, RAG) — sin embedding todavía: "
            "recuperable por término, no por similitud, hasta que se vectorice."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.raw_only and not args.ley_aduanera and not args.ligie:
        raise SystemExit("--ley-aduanera o --ligie es obligatorio salvo con --raw-only")
    if args.chunks and not args.ley_aduanera:
        raise SystemExit("--chunks sólo tiene efecto junto con --ley-aduanera")
    database_url = None if args.raw_only else _database_url(args.target)
    minio_target = _minio_target(args.target)

    log.info("diputados.cli.start", target=args.target)

    with tempfile.TemporaryDirectory(prefix="diputados_") as tmp:
        tmp_path = Path(tmp)

        ley_aduanera_bytes = raw.fetch(load.LEY_ADUANERA_SOURCE_URL)
        ley_aduanera_capture = raw.store_raw_bytes(
            ley_aduanera_bytes,
            source_url=load.LEY_ADUANERA_SOURCE_URL,
            minio_key=LEY_ADUANERA_KEY,
            target=minio_target,
        )
        ley_aduanera_path = tmp_path / "ley_aduanera.pdf"
        ley_aduanera_path.write_bytes(ley_aduanera_bytes)

        ligie_bytes = raw.fetch(load.LIGIE_ARTICULO1_SOURCE_URL)
        ligie_capture = raw.store_raw_bytes(
            ligie_bytes,
            source_url=load.LIGIE_ARTICULO1_SOURCE_URL,
            minio_key=LIGIE_ARTICULO1_KEY,
            target=minio_target,
        )
        ligie_path = tmp_path / "ligie.pdf"
        ligie_path.write_bytes(ligie_bytes)

        for key in (LEY_ADUANERA_KEY, LIGIE_ARTICULO1_KEY):
            raw.verify_stored(target=minio_target, minio_key=key)

        if args.raw_only:
            for capture in (ley_aduanera_capture, ligie_capture):
                print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
            log.info("diputados.cli.done", target=args.target, raw_only=True)
            return 0

        articulos_ley_aduanera = None
        if args.ley_aduanera:
            lines = ley_aduanera.extract_text(str(ley_aduanera_path))
            articulos_ley_aduanera = ley_aduanera.parse_articles(lines)

        articulos_ligie = None
        if args.ligie:
            ligie_lines = ligie.extract_text(str(ligie_path))
            articulos_ligie = ligie.parse_preambulo_y_articulo1(ligie_lines)

    if articulos_ley_aduanera is not None:
        print(f"Parseado: {len(articulos_ley_aduanera)} artículos de la Ley Aduanera.")
    if articulos_ligie is not None:
        print(f"Parseado: {len(articulos_ligie)} elementos del preámbulo/Artículo 1 de la LIGIE.")

    assert database_url is not None  # solo llegamos aquí sin --raw-only
    engine = create_engine(database_url)
    with Session(engine) as session:
        n_articulos = None
        n_chunks = None
        if articulos_ley_aduanera is not None:
            n_articulos = load.load_ley_aduanera(
                session,
                articulos=articulos_ley_aduanera,
                content_hash=ley_aduanera_capture.content_hash,
                retrieved_at=ley_aduanera_capture.retrieved_at,
            )
            if args.chunks:
                n_chunks = load.load_ley_aduanera_chunks(
                    session,
                    articulos=articulos_ley_aduanera,
                    content_hash=ley_aduanera_capture.content_hash,
                    retrieved_at=ley_aduanera_capture.retrieved_at,
                )

        n_ligie = None
        if articulos_ligie is not None:
            n_ligie = load.load_ligie_preambulo_y_articulo1(
                session,
                articulos=articulos_ligie,
                content_hash=ligie_capture.content_hash,
                retrieved_at=ligie_capture.retrieved_at,
            )
        session.commit()

    if n_articulos is not None:
        print(f"OK ({args.target}): {n_articulos} artículos insertados en regulatory.legal_rules.")
    if n_chunks is not None:
        print(f"OK ({args.target}): {n_chunks} chunks insertados en regulatory.legal_chunks.")
    if n_ligie is not None:
        print(
            f"OK ({args.target}): {n_ligie} filas de preámbulo/Artículo 1 de la LIGIE "
            "insertadas en regulatory.legal_rules."
        )
    log.info(
        "diputados.cli.done",
        target=args.target,
        articulos=n_articulos,
        chunks=n_chunks,
        ligie=n_ligie,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
