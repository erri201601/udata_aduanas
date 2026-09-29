"""CLI de ingesta del DOF (Anexo 22 y RGCE 2026): RAW -> PARSED -> DATABASE.

Mismo contrato que `ingestion.snice.cli`: `--target` es obligatorio y mueve
AMBOS destinos (base y MinIO) juntos, y el RAW se verifica en el destino
antes de escribir una sola fila (regla 7 CLAUDE.md; Persona 1, 2026-09-08).
Ambos RAW se suben siempre, se pida o no su carga; sólo se parsea y carga lo
que el flag pide -- igual que `ingestion.diputados.cli`.

Uso:
    python -m ingestion.dof.cli --target local  --anexo22
    python -m ingestion.dof.cli --target local  --rgce
    python -m ingestion.dof.cli --target shared --rgce --chunks
    python -m ingestion.dof.cli --target shared --split-long-rules
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

from ingestion.dof import anexo22, load, rgce
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.dof.cli")

ANEXO22_KEY = "dof/anexo22_20260115.pdf"
RGCE_KEY = "dof/rgce_2026.html"


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
        "--anexo22",
        action="store_true",
        help="Carga los 4 catálogos del Anexo 22 (aduanas, unidades, claves, identificadores).",
    )
    parser.add_argument(
        "--rgce",
        action="store_true",
        help=(
            "Carga las reglas de las RGCE 2026 a regulatory.legal_rules. Las 13 del "
            "Transitorio Cuarto (vigencia en términos de otro decreto no almacenado) "
            "se excluyen y se reportan: no se les inventa fecha."
        ),
    )
    parser.add_argument(
        "--chunks",
        action="store_true",
        help=(
            "Con --rgce, además carga un chunk por regla en regulatory.legal_chunks "
            "(§27, RAG) — sin embedding todavía: recuperable por término."
        ),
    )
    parser.add_argument(
        "--split-long-rules",
        action="store_true",
        help=(
            "Sólo agrega chunks por fracción a reglas RGCE ya cargadas que no "
            "cupieron en el embedder (1.1.6, 4.5.31, 7.3.3) -- no toca "
            "regulatory.legal_rules ni el chunk de la regla completa, no es un "
            "--reset. Idempotente."
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
    if not args.raw_only and not args.anexo22 and not args.rgce and not args.split_long_rules:
        raise SystemExit(
            "--anexo22, --rgce o --split-long-rules es obligatorio salvo con --raw-only"
        )
    if args.chunks and not args.rgce:
        raise SystemExit("--chunks sólo tiene efecto junto con --rgce")
    database_url = None if args.raw_only else _database_url(args.target)
    minio_target = _minio_target(args.target)

    log.info("dof.cli.start", target=args.target)

    with tempfile.TemporaryDirectory(prefix="dof_") as tmp:
        tmp_path = Path(tmp)

        anexo22_bytes = raw.fetch(load.ANEXO22_SOURCE_URL)
        anexo22_capture = raw.store_raw_bytes(
            anexo22_bytes,
            source_url=load.ANEXO22_SOURCE_URL,
            minio_key=ANEXO22_KEY,
            target=minio_target,
        )
        anexo22_path = tmp_path / "anexo22.pdf"
        anexo22_path.write_bytes(anexo22_bytes)

        rgce_bytes = raw.fetch(load.RGCE_SOURCE_URL)
        rgce_capture = raw.store_raw_bytes(
            rgce_bytes,
            source_url=load.RGCE_SOURCE_URL,
            minio_key=RGCE_KEY,
            target=minio_target,
        )

        for key in (ANEXO22_KEY, RGCE_KEY):
            raw.verify_stored(target=minio_target, minio_key=key)

        if args.raw_only:
            for capture in (anexo22_capture, rgce_capture):
                print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
            log.info("dof.cli.done", target=args.target, raw_only=True)
            return 0

        offices = units = claves = regulations = identifiers = None
        if args.anexo22:
            lines = anexo22.extract_text(str(anexo22_path))
            headings = anexo22.find_appendix_headings(lines)
            offices = anexo22.parse_customs_offices(anexo22.appendix_block(lines, headings, 1))
            units = anexo22.parse_units_of_measure(anexo22.appendix_block(lines, headings, 7))
            claves = anexo22.parse_pedimento_claves(anexo22.appendix_block(lines, headings, 2))
            regulations = anexo22.parse_non_tariff_regulations(
                anexo22.appendix_block(lines, headings, 9)
            )
            identifiers = anexo22.parse_identifiers(anexo22.appendix_block(lines, headings, 8))

        reglas = None
        if args.rgce or args.split_long_rules:
            # El meta del HTML dice iso-8859-1, pero los bytes son UTF-8 estricto
            # (verificado contra el documento real): decodificar como latin-1
            # convertiría cada acento en dos caracteres basura.
            reglas = rgce.parse_rules(rgce_bytes.decode("utf-8"))

    if (
        offices is not None
        and units is not None
        and claves is not None
        and regulations is not None
        and identifiers is not None
    ):
        print(
            f"Parseado: {len(offices)} aduanas/secciones, {len(units)} unidades de medida, "
            f"{len(claves)} claves de pedimento (solo código), "
            f"{len(regulations)} identificadores no arancelarios, "
            f"{len(identifiers)} identificadores de pedimento (Apéndice 8)."
        )
    if reglas is not None:
        print(f"Parseado: {len(reglas)} reglas de las RGCE 2026.")

    assert database_url is not None  # solo llegamos aquí sin --raw-only
    engine = create_engine(database_url)

    if args.split_long_rules:
        assert reglas is not None
        with Session(engine) as session:
            n_fraccion_chunks = load.add_fraccion_chunks_for_long_rules(
                session,
                reglas=reglas,
                content_hash=rgce_capture.content_hash,
                retrieved_at=rgce_capture.retrieved_at,
            )
            session.commit()
        print(
            f"--split-long-rules ({args.target}): {n_fraccion_chunks} chunks de fracción agregados."
        )
        log.info("dof.rgce.cli.split_long_rules", target=args.target, creados=n_fraccion_chunks)
        return 0

    with Session(engine) as session:
        if offices is not None and units is not None and claves is not None:
            assert regulations is not None
            assert identifiers is not None
            n_offices, n_units, n_claves, n_regs, n_ids = load.load_anexo22(
                session,
                offices=offices,
                units=units,
                claves=claves,
                regulations=regulations,
                identifiers=identifiers,
                content_hash=anexo22_capture.content_hash,
                retrieved_at=anexo22_capture.retrieved_at,
            )
            print(
                f"OK ({args.target}): {n_offices} aduanas/secciones, {n_units} unidades, "
                f"{n_claves} claves, {n_regs} identificadores no arancelarios, "
                f"{n_ids} identificadores de pedimento insertados."
            )
            log.info(
                "dof.anexo22.cli.done",
                target=args.target,
                offices=n_offices,
                units=n_units,
                claves=n_claves,
                regulations=n_regs,
                identifiers=n_ids,
            )

        if reglas is not None:
            n_reglas, excluidas = load.load_rgce(
                session,
                reglas=reglas,
                content_hash=rgce_capture.content_hash,
                retrieved_at=rgce_capture.retrieved_at,
            )
            print(
                f"OK ({args.target}): {n_reglas} reglas RGCE insertadas en regulatory.legal_rules."
            )
            if excluidas:
                print(
                    f"EXCLUIDAS ({len(excluidas)}, needs_validation, sin valid_from inventado): "
                    + ", ".join(r.rule_number for r in excluidas)
                )
            n_chunks = None
            if args.chunks:
                n_chunks = load.load_rgce_chunks(
                    session,
                    reglas=reglas,
                    content_hash=rgce_capture.content_hash,
                    retrieved_at=rgce_capture.retrieved_at,
                )
                print(f"OK ({args.target}): {n_chunks} chunks RGCE insertados.")
            log.info(
                "dof.rgce.cli.done",
                target=args.target,
                reglas=n_reglas,
                excluidas=[r.rule_number for r in excluidas],
                chunks=n_chunks,
            )
        session.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
