"""Vectoriza los casos comparables sin vector (ADR 0019).

Qué se vectoriza: el asunto más el extracto literal (`criterio_de`), no el
texto entero. Es lo que dice QUÉ mercancía era y cómo se clasificó. El texto
completo trae membretes, direcciones y la cortesía final, que sólo meten ruido
en el parecido con una ficha.

Mismo patrón que `rag.backfill_embeddings`: sólo filas con `embedding IS NULL`
y `commit()` por lote. Una corrida interrumpida conserva lo hecho y la
siguiente retoma lo que falta.

Uso:
    python -m ingestion.cbp_cross.vectores --target local
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from apps.api.logging import con_corrida, registrar
from core.llm.registry import build_provider
from database.models import ComparableRuling
from database.repositories.comparables import texto_para_vector
from rag.embedder import PROVEEDOR_DE_EMBEDDINGS
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from core.llm.base import HTTPModelProvider

log = structlog.stdlib.get_logger("ingestion.cbp_cross.vectores")


def vectorizar(session: Session, *, provider: HTTPModelProvider, lote: int = 50) -> int:
    """Vectoriza lo que falta. Devuelve cuántas filas vectorizó."""
    filas = session.scalars(
        sa.select(ComparableRuling).where(ComparableRuling.embedding.is_(None))
    ).all()
    hechas = 0
    for i, fila in enumerate(filas, start=1):
        fila.embedding = list(provider.embed(texto_para_vector(fila.subject, fila.full_text)))
        hechas += 1
        if i % lote == 0:
            session.commit()
            log.info("cbp_cross.vectores.progreso", n=i, total=len(filas))
    session.commit()
    return hechas


@con_corrida("ingestion.cbp_cross.vectores")
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["local"])
    parser.parse_args(argv)
    provider = build_provider(name=PROVEEDOR_DE_EMBEDDINGS)
    with Session(create_engine(get_settings().sqlalchemy_url)) as session:
        hechas = vectorizar(session, provider=provider)
    registrar(records=hechas)
    print(f"OK (local): {hechas} casos comparables vectorizados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
