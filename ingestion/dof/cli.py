"""CLI de ingesta del Anexo 22: RAW -> PARSED -> VALIDATED -> DATABASE.

Mismo contrato que `ingestion.snice.cli`: `--target` es obligatorio y mueve
AMBOS destinos (base y MinIO) juntos, y el RAW se verifica en el destino
antes de escribir una sola fila (regla 7 CLAUDE.md; Persona 1, 2026-09-08).

Uso:
    python -m ingestion.dof.cli --target local
    python -m ingestion.dof.cli --target shared
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

from ingestion.dof import anexo22, load
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.dof.cli")

ANEXO22_KEY = "dof/anexo22_20260115.pdf"


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database_url = None if args.raw_only else _database_url(args.target)
    minio_target = _minio_target(args.target)

    log.info("dof.anexo22.cli.start", target=args.target)

    with tempfile.TemporaryDirectory(prefix="anexo22_") as tmp:
        tmp_path = Path(tmp)

        pdf_bytes = raw.fetch(load.ANEXO22_SOURCE_URL)
        capture = raw.store_raw_bytes(
            pdf_bytes, source_url=load.ANEXO22_SOURCE_URL, minio_key=ANEXO22_KEY, target=minio_target
        )
        pdf_path = tmp_path / "anexo22.pdf"
        pdf_path.write_bytes(pdf_bytes)

        raw.verify_stored(target=minio_target, minio_key=ANEXO22_KEY)

        if args.raw_only:
            print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
            log.info("dof.anexo22.cli.done", target=args.target, raw_only=True)
            return 0

        lines = anexo22.extract_text(str(pdf_path))
        headings = anexo22.find_appendix_headings(lines)

        offices = anexo22.parse_customs_offices(anexo22.appendix_block(lines, headings, 1))
        units = anexo22.parse_units_of_measure(anexo22.appendix_block(lines, headings, 7))
        claves = anexo22.parse_pedimento_claves(anexo22.appendix_block(lines, headings, 2))
        regulations = anexo22.parse_non_tariff_regulations(
            anexo22.appendix_block(lines, headings, 9)
        )

    print(
        f"Parseado: {len(offices)} aduanas/secciones, {len(units)} unidades de medida, "
        f"{len(claves)} claves de pedimento (solo código), "
        f"{len(regulations)} identificadores no arancelarios."
    )

    assert database_url is not None  # solo llegamos aquí sin --raw-only
    engine = create_engine(database_url)
    with Session(engine) as session:
        n_offices, n_units, n_claves, n_regs = load.load_anexo22(
            session,
            offices=offices,
            units=units,
            claves=claves,
            regulations=regulations,
            content_hash=capture.content_hash,
            retrieved_at=capture.retrieved_at,
        )
        session.commit()

    print(
        f"OK ({args.target}): {n_offices} aduanas/secciones, {n_units} unidades, "
        f"{n_claves} claves, {n_regs} identificadores insertados."
    )
    log.info(
        "dof.anexo22.cli.done",
        target=args.target,
        offices=n_offices,
        units=n_units,
        claves=n_claves,
        regulations=n_regs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
