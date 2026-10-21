"""Vigilante del DOF (§11 DOF, §43 Sprint 6): RAW -> PARSED -> DATABASE del
sumario diario.

CLI aparte de `ingestion.dof.cli` a propósito: ese CLI siempre descarga
Anexo 22 + RGCE (dos documentos fijos, cargados una vez); este vigilante
descarga `sumario.xml`, que cambia cada día y no tiene nada que ver con
esos dos documentos -- forzarlo al mismo flujo habría significado
descargar siempre los tres, aunque sólo se quisiera vigilar el día.

Uso:
    python -m ingestion.dof.watcher_cli --target local
    python -m ingestion.dof.watcher_cli --target shared

Pensado para correr una vez al día (cron/scheduler es infraestructura
aparte, no esta tarea) -- `sumario.xml` no tiene parámetro de fecha, así
que sólo puede ver la edición más reciente en el momento en que corre.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from apps.api.config import get_settings
from apps.api.logging import con_corrida, registrar
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.dof import load
from ingestion.dof.sumario import SUMARIO_URL, es_relevante_comercio_exterior, parse_sumario
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.dof.watcher_cli")


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
        "--solo-notas",
        action="store_true",
        help="No lee el sumario: sólo lee las notas de los eventos pendientes (ADR 0022).",
    )
    return parser.parse_args(argv)


def _leer_notas(database_url: str, minio_target: MinioTarget) -> tuple[int, int]:
    """Lee las notas pendientes. Cada nota va a RAW con el hash en la clave."""

    def guardar(datos: bytes, codigo: str) -> str:
        clave = f"dof/notas/{codigo}_{raw.content_hash(datos)[:16]}.html"
        captura = raw.store_raw_bytes(
            datos, source_url=f"dof:{codigo}", minio_key=clave, target=minio_target
        )
        raw.verify_stored(target=minio_target, minio_key=clave)
        return captura.content_hash

    with Session(create_engine(database_url)) as session:
        resultado = load.leer_notas_pendientes(session, descargar=raw.fetch, guardar_raw=guardar)
        session.commit()
    return resultado


@con_corrida("ingestion.dof.watcher")
def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    minio_target = _minio_target(args.target)

    if args.solo_notas:
        leidas, con_fracciones = _leer_notas(_database_url(args.target), minio_target)
        registrar(records=leidas, con_fracciones=con_fracciones)
        print(f"OK ({args.target}): {leidas} notas leídas, {con_fracciones} citan fracciones.")
        return 0

    sumario_bytes = raw.fetch(SUMARIO_URL)
    hoy = datetime.now(UTC).date()
    minio_key = f"dof/sumario_{hoy:%Y%m%d}.xml"
    captura = raw.store_raw_bytes(
        sumario_bytes, source_url=SUMARIO_URL, minio_key=minio_key, target=minio_target
    )
    raw.verify_stored(target=minio_target, minio_key=minio_key)

    if args.raw_only:
        print(f"RAW OK ({args.target}): {captura.minio_key}  sha256={captura.content_hash}")
        log.info("dof.watcher_cli.done", target=args.target, raw_only=True)
        return 0

    items = parse_sumario(sumario_bytes)
    relevantes = [i for i in items if es_relevante_comercio_exterior(i)]
    print(
        f"Parseado: {len(items)} publicaciones del día, {len(relevantes)} de comercio "
        "exterior/aduanas."
    )

    database_url = _database_url(args.target)
    engine = create_engine(database_url)
    with Session(engine) as session:
        creados = load.load_regulatory_events(
            session,
            items=relevantes,
            content_hash=captura.content_hash,
            retrieved_at=captura.retrieved_at,
        )
        session.commit()

    # Y la nota de cada evento nuevo (o pendiente de otra pasada): qué
    # fracciones cita, qué NOM y desde cuándo rige (ADR 0022).
    leidas, con_fracciones = _leer_notas(database_url, minio_target)
    registrar(records=creados, notas_leidas=leidas, con_fracciones=con_fracciones)
    print(
        f"OK ({args.target}): {creados} regulatory_events nuevos; "
        f"{leidas} notas leídas, {con_fracciones} citan fracciones."
    )
    log.info(
        "dof.watcher_cli.done",
        target=args.target,
        total=len(items),
        relevantes=len(relevantes),
        creados=creados,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
