"""CLI de EBTI: diarias de la Comisión → RAW → PARSED → DATABASE (ADR 0020).

Descarga las publicaciones diarias que lista `daily_publications.jsp` (el
último mes), de la más antigua a la más reciente, guarda cada ZIP en MinIO con
el hash en la clave y carga sus BTI. Correrla otra vez no duplica: inserta las
nuevas y actualiza el estado de las ya cargadas.

Uso:
    python -m ingestion.ebti.cli --target local
    python -m ingestion.ebti.cli --target local --ultimas 3
"""

from __future__ import annotations

import argparse
import io
import zipfile

import httpx
import structlog
from apps.api.config import get_settings
from apps.api.logging import con_corrida, registrar
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ingestion.ebti import ebti, load
from ingestion.snice import raw

log = structlog.stdlib.get_logger("ingestion.ebti.cli")


def descargar(cliente: httpx.Client, fecha_publicacion: str) -> bytes:
    """El ZIP de una diaria. La Comisión redirige y pide su cookie: el cliente
    las sigue y las guarda. Lo que no sea un ZIP se rechaza."""
    r = cliente.get(
        f"{ebti.BASE}/ebti_export_management.jsp",
        params={"publicationDate": fecha_publicacion, "message": "extract"},
    )
    r.raise_for_status()
    if not r.content.startswith(b"PK"):
        raise ValueError(f"la diaria {fecha_publicacion} no devolvió un ZIP")
    return r.content


def csv_del_zip(datos: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        nombres = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(nombres) != 1:
            raise ValueError(f"se esperaba un CSV en el ZIP, hay {len(nombres)}")
        return z.read(nombres[0]).decode("utf-8")


@con_corrida("ingestion.ebti")
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["local"])
    parser.add_argument("--ultimas", type=int, default=None, help="Sólo las N más recientes.")
    args = parser.parse_args(argv)

    minio = raw.local_target()
    nuevas = actualizadas = 0
    with (
        httpx.Client(
            timeout=180, follow_redirects=True, headers={"User-Agent": "ADUANERO-OS/0.1"}
        ) as cliente,
        Session(create_engine(get_settings().sqlalchemy_url)) as session,
    ):
        pagina = cliente.get(f"{ebti.BASE}/daily_publications.jsp", params={"Lang": "en"})
        pagina.raise_for_status()
        lista = ebti.publicaciones(pagina.text)
        if args.ultimas is not None:
            lista = lista[-args.ultimas :]
        if not lista:
            raise SystemExit("la página de diarias no lista ninguna publicación")
        for fecha, archivo in lista:
            datos = descargar(cliente, fecha)
            digest = raw.content_hash(datos)
            clave = f"ebti/diarias/{archivo.removesuffix('.zip')}_{digest[:16]}.zip"
            capture = raw.store_raw_bytes(
                datos,
                source_url=f"{ebti.BASE}/daily_publications.jsp#{archivo}",
                minio_key=clave,
                target=minio,
            )
            raw.verify_stored(target=minio, minio_key=clave)
            btis = ebti.parse_csv(csv_del_zip(datos))
            n_nuevas = 0
            for bti in btis:
                if load.cargar(
                    session,
                    bti,
                    content_hash=capture.content_hash,
                    minio_key=clave,
                    retrieved_at=capture.retrieved_at,
                ):
                    n_nuevas += 1
                else:
                    actualizadas += 1
            nuevas += n_nuevas
            session.commit()
            print(f"  {archivo}: {len(btis)} BTI ({n_nuevas} nuevas)")
    registrar(records=nuevas, actualizadas=actualizadas, diarias=len(lista))
    print(
        f"OK ({args.target}): {nuevas} BTI nuevas, {actualizadas} actualizadas, {len(lista)} diarias."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
