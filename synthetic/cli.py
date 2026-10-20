"""Genera el corpus sintético nuevo y lo carga: SOURCE → RAW → PARSED → DATABASE.

`synthetic/` es la pieza SOURCE (§24). Hasta ahora no había forma de cargar lo
que produce: el corpus original se generó fuera y se subió a mano a MinIO.
Aquí se sigue el pipeline del §12 sin saltarse nada:

1. se genera con el FIX real de cada fecha, leído de `regulatory.exchange_rates`
   —nunca un tipo de cambio inventado—;
2. el JSON resultante se guarda en MinIO con su hash y se verifica en el mismo
   destino donde se va a escribir la base;
3. se parsea y carga por el MISMO camino que el corpus original
   (`ingestion.sintetico.corpus_espejo.parse_corpus` y `load.load_corpus`), que
   es aditivo: no toca ni borra lo ya cargado.

Uso:
    python -m synthetic.cli --target local
    python -m synthetic.cli --target local --dry-run     # todo, y rollback al final
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

import structlog
from apps.api.config import get_settings
from database.repositories.exchange import tasa_vigente
from ingestion.sintetico import corpus_espejo, load
from ingestion.snice import raw
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from synthetic.corpus import construir_corpus_nuevo

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

log = structlog.stdlib.get_logger("synthetic.cli")

#: Mismo escenario y semilla que el corpus original: es una ampliación, no otro
#: corpus (plan de Persona 2, `synthetic/README.md`).
SEED = 20260921
#: El nombre lleva el hash del contenido: un corpus regenerado es OTRO RAW, y
#: con un nombre fijo sobrescribía el que ya sostenía los pedimentos cargados
#: (§12: el RAW no se reescribe).
JSON_KEY_PREFIJO = "sintetico/corpus_espejo_v1_ampliacion_"
SOURCE_URL = "synthetic://corpus_espejo_v1/ampliacion_20261013"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["local", "shared"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Genera, guarda el RAW y carga en una transacción que se revierte.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.target == "shared":
        raise SystemExit(
            "En el dev server la base del equipo es --target local (5433). --target "
            "shared es para cargar desde otra máquina, y aún no está implementado aquí."
        )
    minio_target = raw.local_target()
    engine = create_engine(get_settings().sqlalchemy_url)

    with Session(engine) as session:

        def fix(fecha: date) -> Decimal:
            tasa = tasa_vigente(session, on_date=fecha, currency="USD")
            if tasa is None:
                raise SystemExit(
                    f"No hay FIX cargado para {fecha}: no se inventa un tipo de cambio."
                )
            return tasa

        datos = construir_corpus_nuevo(tasa_de_cambio=fix)
        contenido = json.dumps(datos, ensure_ascii=False, sort_keys=True, indent=1).encode()
        clave = f"{JSON_KEY_PREFIJO}{raw.content_hash(contenido)[:16]}.json"
        captura = raw.store_raw_bytes(
            contenido, source_url=SOURCE_URL, minio_key=clave, target=minio_target
        )
        raw.verify_stored(target=minio_target, minio_key=clave)
        print(f"RAW OK: {captura.minio_key}  sha256={captura.content_hash}")

        corpus = corpus_espejo.parse_corpus(datos)
        reporte = load.load_corpus(session, corpus, seed=SEED)
        print(
            f"Pedimentos: {reporte.pedimentos_creados} creados, "
            f"{reporte.pedimentos_saltados} ya estaban · partidas: {reporte.partidas_creadas} · "
            f"ground truth: {reporte.ground_truth_creados} "
            f"({reporte.ground_truth_expected_true} detectables) · "
            f"COVE: {reporte.coves_creados}"
        )
        if args.dry_run:
            session.rollback()
            print("--dry-run: revertido, no se escribió nada en la base.")
        else:
            session.commit()
    log.info("synthetic.cli.done", target=args.target, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
