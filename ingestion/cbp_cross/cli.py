"""CLI de CBP CROSS: SOURCE → RAW → PARSED → DATABASE (ADR 0019).

Cada resolución es su propio documento: su JSON va a MinIO con el hash en la
clave y se verifica allí antes de escribir su fila (regla 7).

Qué partidas se buscan:

- `--partidas 7323,7615` explícitas, o
- `--desde-corpus`: las partidas (4 dígitos) de lo que el sistema declara o
  clasifica hoy, es decir, las de las partidas de pedimento y las de las
  decisiones de clasificación.

Uso:
    python -m ingestion.cbp_cross.cli --target local --desde-corpus
    python -m ingestion.cbp_cross.cli --target local --partidas 7323 --limite 5
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

import httpx
import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from apps.api.logging import con_corrida, registrar
from database.models import ClassificationDecision, PedimentoItem
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.cbp_cross import cross, load
from ingestion.snice import raw

if TYPE_CHECKING:
    from ingestion.snice.raw import MinioTarget

log = structlog.stdlib.get_logger("ingestion.cbp_cross.cli")


def partidas_del_corpus(session: Session) -> list[str]:
    declaradas = session.scalars(
        sa.select(sa.func.left(PedimentoItem.declared_fraction_code, 4)).where(
            PedimentoItem.declared_fraction_code.is_not(None)
        )
    ).all()
    clasificadas = session.scalars(
        sa.select(sa.func.left(ClassificationDecision.fraction_code, 4)).where(
            ClassificationDecision.fraction_code.is_not(None)
        )
    ).all()
    return sorted({p for p in [*declaradas, *clasificadas] if p and len(p) == 4})


@con_corrida("ingestion.cbp_cross")
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["local"])
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--partidas", help="Partidas de 4 dígitos separadas por comas.")
    grupo.add_argument("--desde-corpus", action="store_true")
    parser.add_argument("--limite", type=int, default=None, help="Máximo por partida (pruebas).")
    args = parser.parse_args(argv)

    engine = create_engine(get_settings().sqlalchemy_url)
    minio: MinioTarget = raw.local_target()
    with Session(engine) as session:
        if args.desde_corpus:
            partidas = partidas_del_corpus(session)
        else:
            partidas = [p.strip() for p in args.partidas.split(",") if p.strip()]
        if not partidas or any(len(p) != 4 or not p.isdigit() for p in partidas):
            raise SystemExit(f"partidas inválidas: {partidas!r} (cuatro dígitos cada una)")
        print(f"Partidas: {', '.join(partidas)}")

        nuevas = actualizadas = omitidas = 0
        vistas: set[str] = set()
        with httpx.Client(timeout=60, headers={"User-Agent": "ADUANERO-OS/0.1"}) as cliente:
            for partida in partidas:
                encontradas = 0
                for resumen in cross.buscar(cliente, partida):
                    numero = str(resumen.get("rulingNumber") or "")
                    if not numero or numero in vistas:
                        continue
                    if args.limite is not None and encontradas >= args.limite:
                        break
                    vistas.add(numero)
                    encontradas += 1
                    datos = cross.detalle(cliente, numero)
                    try:
                        resolucion = cross.parse(json.loads(datos))
                    except (cross.ResolucionIlegibleError, ValueError) as exc:
                        omitidas += 1
                        log.warning("cbp_cross.omitida", numero=numero, error=str(exc))
                        continue
                    digest = raw.content_hash(datos)
                    clave = (
                        f"cbp_cross/{resolucion.collection or 'sin_coleccion'}/"
                        f"{numero}_{digest[:16]}.json"
                    )
                    capture = raw.store_raw_bytes(
                        datos, source_url=resolucion.url, minio_key=clave, target=minio
                    )
                    raw.verify_stored(target=minio, minio_key=clave)
                    if load.cargar(
                        session,
                        resolucion,
                        content_hash=capture.content_hash,
                        minio_key=clave,
                        retrieved_at=capture.retrieved_at,
                    ):
                        nuevas += 1
                    else:
                        actualizadas += 1
                session.commit()
                print(f"  {partida}: {encontradas} resoluciones")
    registrar(records=nuevas, errors=omitidas, actualizadas=actualizadas, partidas=len(partidas))
    print(
        f"OK ({args.target}): {nuevas} nuevas, {actualizadas} ya estaban, "
        f"{omitidas} omitidas por ilegibles."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
