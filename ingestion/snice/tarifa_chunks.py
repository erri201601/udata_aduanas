"""Los textos de la tarifa en la búsqueda jurídica (§27): un fragmento por partida.

De la LIGIE, el RAG sólo tenía las 92 notas de sección y capítulo. Los textos de
las 1 236 partidas, 5 619 subpartidas y 8 136 fracciones estaban en
`tariff_headings` y `tariff_fractions` —los usa el motor RGI— pero el Copilot no
podía recuperarlos. Preguntado por la 7312.10.05 contestaba, con razón, que «los
pasajes no contienen el texto de la partida 73.12». Y es el fundamento de
cualquier clasificación.

POR QUÉ UN FRAGMENTO POR PARTIDA Y NO UNO POR FRACCIÓN

Una fracción suelta dice a menudo «Los demás.», que sin su partida y su
subpartida no significa nada. Se escribe la jerarquía completa —partida,
subpartidas y fracciones, en orden— y la partida es la unidad citable
(«Partida 73.12»). Si una partida pasa de `MAXIMO` caracteres (la 98.02 tiene
38 fracciones) se parte por subpartida, repitiendo el encabezado de la partida.

DE DÓNDE SALE

De las filas vigentes de `tariff_headings` y `tariff_fractions`, que ya pasaron
por RAW → PARSED → DATABASE desde el SNICE (`ingestion.snice`). Esto es el paso
de chunking del §27 sobre documentos normalizados, no una fuente nueva: el
documento es la propia LIGIE, con su vigencia y su URL.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from database.models import LegalChunkRecord, TariffFraction, TariffHeading
from database.repositories.chunks import PostgresChunkStore
from rag.types import LegalChunk, hash_contenido
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.snice.load import (
    LIGIE_SOURCE_URL,
    LIGIE_VALID_FROM,
    get_or_create_ligie_document,
    get_or_create_snice_source,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

log = structlog.stdlib.get_logger("ingestion.snice.tarifa_chunks")

#: Por encima de esto se parte por subpartida. Holgado frente al límite del
#: modelo de embeddings, y corto para que un pasaje se pueda leer entero.
MAXIMO: Final = 6_000


@dataclass(frozen=True)
class Fragmento:
    article: str
    """«Partida 73.12», o «Partida 98.02 (9802.00)» cuando se parte."""
    path: str
    text: str


def _punteada(codigo: str) -> str:
    """«7312» → «73.12»; «731210» → «7312.10»; «73121005» → «7312.10.05»."""
    if len(codigo) == 4:
        return f"{codigo[:2]}.{codigo[2:]}"
    if len(codigo) == 6:
        return f"{codigo[:4]}.{codigo[4:]}"
    return f"{codigo[:4]}.{codigo[4:6]}.{codigo[6:]}"


def fragmentos_de_la_tarifa(
    partidas: Iterable[tuple[str, str]],
    subpartidas: Iterable[tuple[str, str]],
    fracciones: Iterable[tuple[str, str]],
) -> list[Fragmento]:
    """`(código, texto)` de cada nivel → un fragmento por partida.

    Puro: sin base, para poder probarlo. Las subpartidas y fracciones se
    agrupan por los 4 y 6 primeros dígitos de su código.
    """
    subs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for codigo, texto in subpartidas:
        subs[codigo[:4]].append((codigo, texto))
    fracs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for codigo, texto in fracciones:
        fracs[codigo[:6]].append((codigo, texto))

    salida: list[Fragmento] = []
    for partida, texto_partida in sorted(partidas):
        encabezado = f"{_punteada(partida)} {texto_partida}"
        bloques: list[tuple[str, str]] = []
        for sub, texto_sub in sorted(subs.get(partida, [])):
            lineas = [f"  {_punteada(sub)} {texto_sub}"]
            lineas += [f"    {_punteada(f)} {t}" for f, t in sorted(fracs.get(sub, []))]
            bloques.append((sub, "\n".join(lineas)))
        # Fracciones colgadas directamente de la partida (subpartida «.00»
        # sin texto propio en `tariff_headings`).
        sueltas = sorted(
            (f, t)
            for s, lista in fracs.items()
            if s[:4] == partida and s not in dict(bloques)
            for f, t in lista
        )
        if sueltas:
            bloques.append(
                (partida + "00", "\n".join(f"    {_punteada(f)} {t}" for f, t in sueltas))
            )

        completo = "\n".join([encabezado, *(b for _, b in bloques)])
        capitulo = partida[:2]
        if len(completo) <= MAXIMO:
            salida.append(
                Fragmento(
                    article=f"Partida {_punteada(partida)}",
                    path=f"Capítulo {capitulo} > Partida {_punteada(partida)}",
                    text=completo,
                )
            )
            continue
        for sub, bloque in bloques:
            salida.append(
                Fragmento(
                    article=f"Partida {_punteada(partida)} ({_punteada(sub)})",
                    path=f"Capítulo {capitulo} > Partida {_punteada(partida)} > {_punteada(sub)}",
                    text=f"{encabezado}\n{bloque}",
                )
            )
    return salida


def cargar(session: Session) -> int:
    """Escribe los fragmentos que falten en `legal_chunks`. Idempotente.

    Cada fragmento avisa `chunks.sin_norma_detras`: el almacén busca una fila de
    `legal_rules` detrás, y las partidas no la tienen por diseño (ADR 0002, su
    texto vive en `tariff_headings`). Es esperado y no afecta a la búsqueda.
    """
    vigente = sa.and_(TariffHeading.valid_to.is_(None))
    partidas = (
        session.execute(
            sa.select(TariffHeading.code, TariffHeading.description).where(
                vigente, sa.func.length(TariffHeading.code) == 4
            )
        )
        .tuples()
        .all()
    )
    subpartidas = (
        session.execute(
            sa.select(TariffHeading.code, TariffHeading.description).where(
                vigente, sa.func.length(TariffHeading.code) == 6
            )
        )
        .tuples()
        .all()
    )
    fracciones = (
        session.execute(
            sa.select(TariffFraction.code, TariffFraction.description).where(
                TariffFraction.valid_to.is_(None)
            )
        )
        .tuples()
        .all()
    )
    fragmentos = fragmentos_de_la_tarifa(partidas, subpartidas, fracciones)

    hash_ligie = session.scalar(
        sa.select(TariffFraction.content_hash).where(TariffFraction.valid_to.is_(None)).limit(1)
    )
    source = get_or_create_snice_source(session)
    documento = get_or_create_ligie_document(
        session, source, content_hash=hash_ligie or "", retrieved_at=datetime.now(UTC)
    )
    # `PostgresChunkStore.add` no salta los existentes: una segunda carga
    # chocaría con la clave única (documento, artículo, vigencia).
    ya = set(
        session.scalars(
            sa.select(LegalChunkRecord.article).where(
                LegalChunkRecord.legal_document_id == documento.id,
                LegalChunkRecord.valid_from == LIGIE_VALID_FROM,
            )
        )
    )
    chunks = [
        LegalChunk(
            source_id=source.id,
            document_id=documento.id,
            document=documento.title,
            article=f.article,
            path=f.path,
            text=f.text,
            content_hash=hash_contenido(f.text),
            data_origin="OFFICIAL",
            valid_from=LIGIE_VALID_FROM,
            url=LIGIE_SOURCE_URL,
        )
        for f in fragmentos
        if f.article not in ya
    ]
    creados = PostgresChunkStore(session).add(chunks)
    log.info("snice.tarifa_chunks.cargado", fragmentos=len(fragmentos), creados=creados)
    return creados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["local"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    with Session(create_engine(get_settings().sqlalchemy_url)) as session:
        creados = cargar(session)
        if args.dry_run:
            session.rollback()
            print(f"--dry-run: {creados} fragmentos se crearían; revertido.")
        else:
            session.commit()
            print(f"OK ({args.target}): {creados} fragmentos de la tarifa en legal_chunks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
