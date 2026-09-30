"""CLI de ingesta SNICE: RAW -> PARSED -> NORMALIZED -> VALIDATED -> DATABASE.

El destino (`local` / `shared`) es un argumento obligatorio, nunca un default
silencioso: escribir en la base compartida del equipo debe ser una decisión
visible en la línea de comandos, no algo que pasa porque una variable de
entorno estaba puesta (Persona 1, 2026-09-07).

`--target` redirige AMBOS destinos, base y MinIO, juntos — nunca uno sí y el
otro no. Antes de escribir en la base de `--target`, se verifica que el RAW
ya exista en el MinIO de ESE MISMO destino: sin esa verificación, nada
impedía que el RAW subiera a un MinIO y las filas a la base de otro, que es
justo lo que pasó una vez (Persona 1, 2026-09-08).

Uso:
    python -m ingestion.snice.cli --target local  --chapters 84 85
    python -m ingestion.snice.cli --target shared --chapters 84 85

`--raw-only` sube el RAW y verifica, sin tocar la base — para recapturar el
crudo en un destino cuyos datos ya están cargados (Persona 1, 2026-09-08:
el RAW nunca llegó al MinIO compartido aunque las filas sí a la base).

`--target local` usa `DATABASE_URL`/`POSTGRES_*` y el MinIO de tu `.env`
(siempre local). `--target shared` exige `ADUANERO_SHARED_URL` y
`ADUANERO_SHARED_MINIO_URL` en el entorno — nunca los escribas ni los pegues
en un chat; ponlos en tu `.env` cuando Persona 1 te dé las credenciales por
canal seguro.
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

from ingestion.snice import load, nico, notes, raw, tariff, tariff_headings

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

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


def _minio_target(target: str) -> MinioTarget:
    """El mismo `--target` decide dónde va el RAW — nunca queda fijo en local."""
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
        "--chapters",
        required=False,
        nargs="+",
        metavar="NN",
        help="Capítulos de 2 dígitos a cargar, p. ej. --chapters 84 85 (ignorado con --raw-only)",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Solo sube y verifica el RAW en --target; no toca la base.",
    )
    parser.add_argument(
        "--notes",
        action="store_true",
        help=(
            "Carga las notas de Sección y de Capítulo de la LIGIE completa a "
            "regulatory.legal_rules (no filtra por --chapters: son el corpus "
            "completo del documento, no de los capítulos ya cargados)."
        ),
    )
    parser.add_argument(
        "--chunks",
        action="store_true",
        help=(
            "Con --notes, además carga un chunk por nota en regulatory.legal_chunks "
            "(§27, RAG) — sin embedding todavía: recuperable por término, no por "
            "similitud, hasta que se vectorice."
        ),
    )
    parser.add_argument(
        "--headings",
        action="store_true",
        help=(
            "Carga partidas (4 dígitos) y subpartidas (6) a "
            "regulatory.tariff_headings (ADR 0002) — recorre la LIGIE completa "
            "con pdftotext -bbox-layout, ~90s. No filtra por --chapters: son el "
            "documento completo, igual que --notes."
        ),
    )
    parser.add_argument(
        "--heading-groups",
        action="store_true",
        help=(
            "Backfill DIRIGIDO de niveles de un guion (ADR 0004) a "
            "regulatory.tariff_heading_groups: sólo agrega lo que falte, no "
            "vuelve a cargar tariff_headings completa -- ésa ya debe estar "
            "cargada (--headings, en una corrida previa). Idempotente."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if (
        not args.raw_only
        and not args.chapters
        and not args.notes
        and not args.headings
        and not args.heading_groups
    ):
        raise SystemExit(
            "--chapters, --notes, --headings o --heading-groups es obligatorio salvo con --raw-only"
        )
    if args.chunks and not args.notes:
        raise SystemExit("--chunks sólo tiene efecto junto con --notes")
    chapters = frozenset(args.chapters or ())
    # `--raw-only` no toca la base: no le exigimos su URL, que puede no
    # estar configurada si solo se va a recapturar el crudo.
    database_url = None if args.raw_only else _database_url(args.target)
    minio_target = _minio_target(args.target)

    log.info("snice.cli.start", target=args.target, chapters=sorted(chapters))

    with tempfile.TemporaryDirectory(prefix="snice_") as tmp:
        tmp_path = Path(tmp)

        tarifa_key = "snice/fracciones_20260420.xlsx"
        tarifa_bytes = raw.fetch(TARIFA_URL)
        tarifa_capture = raw.store_raw_bytes(
            tarifa_bytes, source_url=TARIFA_URL, minio_key=tarifa_key, target=minio_target
        )
        tarifa_path = tmp_path / "fracciones.xlsx"
        tarifa_path.write_bytes(tarifa_bytes)

        nico_key = "snice/nico_20240415.xlsx"
        nico_bytes = raw.fetch(NICO_URL)
        nico_capture = raw.store_raw_bytes(
            nico_bytes, source_url=NICO_URL, minio_key=nico_key, target=minio_target
        )
        nico_path = tmp_path / "nico.xlsx"
        nico_path.write_bytes(nico_bytes)

        ligie_key = "snice/ligie_unificada_20250728.pdf"
        ligie_bytes = raw.fetch(LIGIE_PDF_URL)
        ligie_capture = raw.store_raw_bytes(
            ligie_bytes, source_url=LIGIE_PDF_URL, minio_key=ligie_key, target=minio_target
        )
        ligie_path = tmp_path / "ligie.pdf"
        ligie_path.write_bytes(ligie_bytes)

        # Guardia explícita: el RAW tiene que existir en ESTE MISMO destino
        # antes de escribir una sola fila en su base (regla 7 CLAUDE.md).
        for key in (tarifa_key, nico_key, ligie_key):
            raw.verify_stored(target=minio_target, minio_key=key)

        if args.raw_only:
            for capture in (tarifa_capture, nico_capture, ligie_capture):
                print(f"RAW OK ({args.target}): {capture.minio_key}  sha256={capture.content_hash}")
            log.info("snice.cli.done", target=args.target, raw_only=True)
            return 0

        fa_result = None
        nico_result = None
        if chapters:
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

        parsed_notes = None
        if args.notes:
            ligie_lines = notes.extract_text(str(ligie_path))
            parsed_notes = notes.parse_notes(ligie_lines)

        parsed_headings = None
        parsed_groups = None
        subheading_to_group = None
        if args.heading_groups:
            # Una sola pasada para las dos cosas (ver docstring de
            # `parse_headings_con_grupos`) -- si además se pidió --headings,
            # no se vuelve a recorrer el documento para lo mismo.
            parsed_headings, parsed_groups, subheading_to_group = (
                tariff_headings.parse_headings_con_grupos(str(ligie_path))
            )
        elif args.headings:
            parsed_headings = tariff_headings.parse_headings(str(ligie_path))

    if fa_result is not None and nico_result is not None:
        fa_declared = len(fa_result.accepted) + len(fa_result.rejected)
        nico_declared = len(nico_result.accepted) + len(nico_result.rejected)
        print(f"Reconciliación tarifa: {fa_result.reconciliation(declared_by_source=fa_declared)}")
        print(
            f"Reconciliación NICO:   {nico_result.reconciliation(declared_by_source=nico_declared)}"
        )
        if fa_result.rate_warnings:
            print(f"Advertencias de tasa: {len(fa_result.rate_warnings)}")
    if parsed_notes is not None:
        print(f"Notas parseadas: {len(parsed_notes)} (Secciones y Capítulos con bloque de notas).")
    if parsed_headings is not None:
        n_partidas = sum(1 for h in parsed_headings if h.level == 4)
        n_subpartidas = sum(1 for h in parsed_headings if h.level == 6)
        print(
            f"Partidas/subpartidas parseadas: {n_partidas} partidas, {n_subpartidas} subpartidas."
        )
    if parsed_groups is not None and subheading_to_group is not None:
        print(
            f"Grupos de guion parseados: {len(parsed_groups)}, "
            f"{len(subheading_to_group)} subpartidas asociadas a alguno."
        )

    assert database_url is not None  # solo llegamos aquí sin --raw-only
    engine = create_engine(database_url)
    with Session(engine) as session:
        if fa_result is not None and nico_result is not None:
            n_fracciones, n_nicos = load.load_chapters(
                session,
                fracciones=fa_result.accepted,
                nicos=nico_result.accepted,
                ligie_content_hash=ligie_capture.content_hash,
            )
            print(f"OK ({args.target}): {n_fracciones} fracciones, {n_nicos} NICO insertados.")
            log.info("snice.cli.done", target=args.target, fracciones=n_fracciones, nicos=n_nicos)
        if parsed_notes is not None:
            n_notas = load.load_ligie_notes(
                session, notes=parsed_notes, ligie_content_hash=ligie_capture.content_hash
            )
            print(f"OK ({args.target}): {n_notas} notas de Sección/Capítulo insertadas.")
            log.info("snice.cli.done", target=args.target, notas=n_notas)
            if args.chunks:
                n_chunks = load.load_ligie_notes_chunks(
                    session, notes=parsed_notes, ligie_content_hash=ligie_capture.content_hash
                )
                print(f"OK ({args.target}): {n_chunks} chunks de notas insertados.")
                log.info("snice.cli.done", target=args.target, chunks=n_chunks)
        if args.headings:
            assert parsed_headings is not None
            n_headings = load.load_tariff_headings(
                session, headings=parsed_headings, ligie_content_hash=ligie_capture.content_hash
            )
            print(f"OK ({args.target}): {n_headings} partidas/subpartidas insertadas.")
            log.info("snice.cli.done", target=args.target, headings=n_headings)
        if args.heading_groups:
            assert parsed_groups is not None
            assert subheading_to_group is not None
            reporte = load.add_missing_heading_groups(
                session,
                groups=parsed_groups,
                subheading_to_group=subheading_to_group,
                ligie_content_hash=ligie_capture.content_hash,
            )
            print(
                f"OK ({args.target}): {reporte.grupos_creados} grupos de guion creados, "
                f"{reporte.subpartidas_asociadas} subpartidas asociadas."
            )
            if reporte.necesitan_validacion:
                print(f"NEEDS_VALIDATION ({len(reporte.necesitan_validacion)}):")
                for linea in reporte.necesitan_validacion:
                    print(f"  - {linea}")
            log.info(
                "snice.cli.done",
                target=args.target,
                grupos_creados=reporte.grupos_creados,
                subpartidas_asociadas=reporte.subpartidas_asociadas,
                necesitan_validacion=len(reporte.necesitan_validacion),
            )
        session.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
