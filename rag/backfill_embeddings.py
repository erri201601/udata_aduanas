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
from core.llm.errors import ProviderResponseError
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


def backfill(session: Session, *, provider: HTTPModelProvider, commit_every: int = 50) -> int:
    """Vectoriza los chunks con `embedding IS NULL`. Devuelve cuántos tocó.

    `commit_every` NO agrupa llamadas a la API —`Embedder.embed()` recibe un
    texto, no una lista, así que siempre son N llamadas HTTP secuenciales—:
    agrupa cuándo se hace durable lo ya vectorizado.

    `session.commit()` en vez de `flush()` a propósito (hallazgo real de
    Ulises, 2026-09-08): `flush()` manda el UPDATE pero no lo hace durable —
    si `provider.embed()` lanza más adelante (un 429, por ejemplo) y nadie
    más hace `commit()`, `Session.__exit__` cierra sin confirmar y hasta lo
    ya *enviado* se revierte. Pagado a OpenAI, cero persistido, y el
    reintento vuelve a pagar por lo mismo. Con `commit()` por lote, una
    corrida interrumpida conserva lo que ya vectorizó, y como la consulta
    filtra por `embedding IS NULL`, volver a lanzarla retoma sólo lo que
    falta — reanudación sin ninguna bandera nueva.
    """
    filas = session.scalars(
        sa.select(LegalChunkRecord).where(LegalChunkRecord.embedding.is_(None))
    ).all()
    vectorizados = 0
    demasiado_largos: list[tuple[str, int]] = []
    for i, fila in enumerate(filas, start=1):
        try:
            fila.embedding = provider.embed(fila.text)
        except ProviderResponseError as exc:
            if not _excede_el_contexto(exc):
                raise
            # Ni se trunca ni se parte aquí. Un vector de media norma haría
            # que una búsqueda casara con lo que sí entró y no con lo que
            # quedó fuera, sin que nadie pudiera notarlo: peor que no tener
            # vector, porque el que falta se busca por término y éste
            # mentiría en silencio. Se salta, se cuenta y se dice cuál.
            demasiado_largos.append((fila.article or str(fila.id), len(fila.text)))
            log.warning(
                "backfill_embeddings.chunk_demasiado_largo",
                articulo=fila.article,
                caracteres=len(fila.text),
            )
            continue
        vectorizados += 1
        if i % commit_every == 0:
            session.commit()
            log.info("backfill_embeddings.progreso", n=i, total=len(filas))
    session.commit()

    if demasiado_largos:
        log.warning(
            "backfill_embeddings.saltados",
            cuantos=len(demasiado_largos),
            de=len(filas),
            detalle=[f"{a} ({n} caracteres)" for a, n in demasiado_largos],
        )
    return vectorizados


#: Lo que responde OpenAI cuando el texto pasa del contexto del modelo de
#: embeddings. Se reconoce por el mensaje porque el error llega con HTTP 400
#: genérico, sin un código que lo distinga de otros 400.
_EXCESO_DE_CONTEXTO = "maximum context length"


def _excede_el_contexto(exc: ProviderResponseError) -> bool:
    """¿El fallo es «este texto no cabe» y no otra cosa?

    Sólo ese caso se salta. Un 429, una llave inválida o el proveedor caído
    tienen que seguir tumbando la corrida: reintentar 500 chunks contra un
    proveedor que no responde es pagar por nada.
    """
    return _EXCESO_DE_CONTEXTO in str(exc)


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

    # `backfill()` confirma cada lote por su cuenta: no hay un commit final
    # aquí que dependa de que la corrida entera termine sin errores.
    engine = create_engine(_database_url(args.target))
    with Session(engine) as session:
        n = backfill(session, provider=provider)

    print(f"OK ({args.target}): {n} chunks vectorizados con {provider.default_embedding_model}.")
    log.info("backfill_embeddings.done", target=args.target, n=n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
