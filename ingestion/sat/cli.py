"""CLI de SAT Datos Abiertos: SOURCE → RAW → PARSED → DATABASE (ADR 0021).

Uso:
    python -m ingestion.sat.cli --target local
"""

from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime

import sqlalchemy as sa
import structlog
from apps.api.config import get_settings
from apps.api.logging import con_corrida, registrar
from database.models import TradeStatistic
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.sat import cifras
from ingestion.snice import raw

log = structlog.stdlib.get_logger("ingestion.sat.cli")


def cargar(
    session: Session,
    filas: list[cifras.Cifra],
    *,
    url: str,
    minio_key: str,
    content_hash: str,
    retrieved_at: datetime,
) -> tuple[int, int]:
    """Inserta o actualiza cada cifra. Devuelve `(nuevas, cambiadas)`.

    El SAT revisa cifras preliminares: si el valor cambia, se actualiza y la
    fila apunta al RAW nuevo. Si no cambia, no se toca.
    """
    existentes = {
        (t.series, t.year, t.month): t
        for t in session.scalars(
            sa.select(TradeStatistic).where(TradeStatistic.source == cifras.FUENTE)
        )
    }
    nuevas = cambiadas = 0
    for c in filas:
        fila = existentes.get((c.serie, c.anio, c.mes))
        if fila is not None:
            if fila.value != c.valor or fila.notes != c.notas:
                fila.value, fila.notes = c.valor, c.notas
                fila.content_hash, fila.retrieved_at = content_hash, retrieved_at
                fila.source_document = f"SAT Datos Abiertos ({minio_key})"
                cambiadas += 1
            continue
        session.add(
            TradeStatistic(
                source=cifras.FUENTE,
                series=c.serie,
                year=c.anio,
                month=c.mes,
                value=c.valor,
                unit=c.unidad,
                is_cumulative=c.acumulada,
                notes=c.notas,
                data_origin="OFFICIAL",
                valid_from=date(c.anio, c.mes, 1),
                valid_to=date(c.anio, c.mes, calendar.monthrange(c.anio, c.mes)[1]),
                source_url=url,
                source_document=f"SAT Datos Abiertos ({minio_key})",
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )
        nuevas += 1
    return nuevas, cambiadas


@con_corrida("ingestion.sat")
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["local"])
    parser.parse_args(argv)
    minio = raw.local_target()
    total_nuevas = total_cambiadas = 0
    with Session(create_engine(get_settings().sqlalchemy_url)) as session:
        for archivo in cifras.ARCHIVOS:
            url = f"{cifras.BASE}/{archivo.nombre}"
            datos = raw.fetch(url)
            clave = f"sat/datos_abiertos/{archivo.nombre.removesuffix('.xls')}_{raw.content_hash(datos)[:16]}.xls"
            capture = raw.store_raw_bytes(datos, source_url=url, minio_key=clave, target=minio)
            raw.verify_stored(target=minio, minio_key=clave)
            filas = cifras.leer(datos, archivo)
            nuevas, cambiadas = cargar(
                session,
                filas,
                url=url,
                minio_key=clave,
                content_hash=capture.content_hash,
                retrieved_at=capture.retrieved_at,
            )
            session.commit()
            total_nuevas += nuevas
            total_cambiadas += cambiadas
            print(
                f"  {archivo.nombre}: {len(filas)} cifras ({nuevas} nuevas, {cambiadas} cambiadas)"
            )
    registrar(records=total_nuevas, cambiadas=total_cambiadas)
    print(f"OK (local): {total_nuevas} cifras nuevas, {total_cambiadas} cambiadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
