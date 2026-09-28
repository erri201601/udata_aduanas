"""CLI del corpus espejo V1: RAW (ya en MinIO) -> PARSED -> VALIDATED -> DATABASE.

El RAW ya fue capturado y verificado por Persona 1 directo en el dev server
(regla 7 CLAUDE.md) — este CLI no descarga de ninguna URL externa, sólo lee
lo que ya está en MinIO y confirma con `verify_stored` que sigue ahí, en el
MISMO destino donde va a escribir la base (mismo criterio que
`ingestion.diputados.cli`, por el bug real del 8-sep: RAW en un MinIO,
filas en la base de otro).

Uso:
    python -m ingestion.sintetico.cli --target local
    python -m ingestion.sintetico.cli --target shared
    python -m ingestion.sintetico.cli --target local --reset            # borra y recarga (§24)
    python -m ingestion.sintetico.cli --target shared --fix-missing-info  # sólo corrige fichas
    python -m ingestion.sintetico.cli --target shared --add-coves        # sólo agrega el COVE
"""

from __future__ import annotations

import argparse
import json
import os
from typing import TYPE_CHECKING

import structlog
from apps.api.config import get_settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.sintetico import corpus_espejo, load
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.sintetico.cli")

PDF_KEY = "sintetico/corpus_espejo_v1_20260921.pdf"
JSON_KEY = "sintetico/corpus_espejo_v1_20260921.json"


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
        help="'shared' lee el MinIO/la base del equipo — decisión explícita.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borra la carga anterior de este escenario antes de recargar (§24).",
    )
    parser.add_argument(
        "--fix-missing-info",
        action="store_true",
        help=(
            "Sólo corrige ProductDna.missing_information/ProductAttribute de la carga "
            "existente (bug real del 22-sep-2026) -- no toca pedimentos ni ground_truth, "
            "no es un --reset."
        ),
    )
    parser.add_argument(
        "--add-coves",
        action="store_true",
        help=(
            "Sólo agrega el Cove a facturas de la carga existente que todavía no lo "
            "tenían -- no toca pedimentos, facturas ni ground_truth, no es un --reset."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    minio_target = _minio_target(args.target)
    database_url = _database_url(args.target)

    log.info("sintetico.corpus_espejo.cli.start", target=args.target)

    raw.verify_stored(target=minio_target, minio_key=PDF_KEY)
    raw.verify_stored(target=minio_target, minio_key=JSON_KEY)

    resp = minio_target.client.get_object(minio_target.bucket, JSON_KEY)
    try:
        contenido = resp.read()
    finally:
        resp.close()
        resp.release_conn()

    datos = json.loads(contenido)
    corpus = corpus_espejo.parse_corpus(datos)
    n_partidas = sum(len(p.parts) for p in corpus.pedimentos)
    print(f"Parseado: {len(corpus.pedimentos)} pedimentos, {n_partidas} partidas.")

    engine = create_engine(database_url)

    if args.fix_missing_info:
        with Session(engine) as session:
            n_corregidos = load.fix_missing_information(session, corpus)
            session.commit()
        print(f"--fix-missing-info ({args.target}): {n_corregidos} fichas corregidas.")
        log.info(
            "sintetico.corpus_espejo.cli.fix_missing_info",
            target=args.target,
            corregidos=n_corregidos,
        )
        return 0

    if args.add_coves:
        with Session(engine) as session:
            n_coves = load.add_missing_coves(session, corpus)
            session.commit()
        print(f"--add-coves ({args.target}): {n_coves} COVE agregados.")
        log.info(
            "sintetico.corpus_espejo.cli.add_coves",
            target=args.target,
            creados=n_coves,
        )
        return 0

    with Session(engine) as session:
        if args.reset:
            n_borrados = load.delete_scenario_data(session)
            session.commit()
            print(f"--reset ({args.target}): {n_borrados} pedimentos anteriores borrados.")
        reporte = load.load_corpus(session, corpus)
        session.commit()

    print(
        f"OK ({args.target}): {reporte.pedimentos_creados} pedimentos creados "
        f"({reporte.pedimentos_saltados} ya existían), "
        f"{reporte.partidas_creadas} partidas, "
        f"{reporte.partidas_con_invoice_item} con invoice_item_id, "
        f"{reporte.coves_creados} COVE, "
        f"{reporte.ground_truth_creados} filas de ground truth "
        f"({reporte.ground_truth_expected_true} con expected_detection=true)."
    )
    log.info(
        "sintetico.corpus_espejo.cli.done",
        target=args.target,
        pedimentos_creados=reporte.pedimentos_creados,
        pedimentos_saltados=reporte.pedimentos_saltados,
        partidas_creadas=reporte.partidas_creadas,
        coves_creados=reporte.coves_creados,
        ground_truth_creados=reporte.ground_truth_creados,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
