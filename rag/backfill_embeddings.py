"""Backfill de `embedding` en `regulatory.legal_chunks` (§27).

Los chunks se insertan primero sin vector — cargar el texto y vectorizarlo
son dos fallos que no tienen por qué ocurrir juntos (ver
`database.repositories.chunks`). Esto rellena `embedding` para los que
quedaron `NULL`, sin volver a tocar los que ya lo tienen.

PIDE OPENAI EXPLÍCITAMENTE

`build_provider(name="openai")`, nunca `get_default_provider()`:
`DEFAULT_MODEL_PROVIDER` puede ser `anthropic`, que no ofrece embeddings —
`core/llm/providers/anthropic.py` lanza `ProviderCapabilityError` a propósito
en vez de inventar un vector, y aquí se pide el proveedor correcto desde el
principio en vez de depender de que ese error se dispare (Ulises,
2026-09-08).

Uso:
    python -m rag.backfill_embeddings --target local
    python -m rag.backfill_embeddings --target shared
"""

from __future__ import annotations

import argparse
import os
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from core.llm.registry import build_provider
from database.models import LegalChunkRecord
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from core.llm.base import HTTPModelProvider

log = structlog.stdlib.get_logger("rag.backfill_embeddings")


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


def backfill(session: Session, *, provider: HTTPModelProvider, batch_size: int = 50) -> int:
    """Vectoriza los chunks con `embedding IS NULL`. Devuelve cuántos tocó."""
    filas = session.scalars(
        sa.select(LegalChunkRecord).where(LegalChunkRecord.embedding.is_(None))
    ).all()
    for i, fila in enumerate(filas, start=1):
        fila.embedding = provider.embed(fila.text)
        if i % batch_size == 0:
            session.flush()
            log.info("backfill_embeddings.progreso", n=i, total=len(filas))
    session.flush()
    return len(filas)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        required=True,
        choices=["local", "shared"],
        help="'shared' escribe en la base del equipo — decisión explícita.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    provider = build_provider(name="openai")
    log.info(
        "backfill_embeddings.start", target=args.target, modelo=provider.default_embedding_model
    )

    engine = create_engine(_database_url(args.target))
    with Session(engine) as session:
        n = backfill(session, provider=provider)
        session.commit()

    print(f"OK ({args.target}): {n} chunks vectorizados con {provider.default_embedding_model}.")
    log.info("backfill_embeddings.done", target=args.target, n=n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
