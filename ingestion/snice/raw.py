"""Captura RAW de las fuentes SNICE (LIGIE/TIGIE, NICO) a MinIO.

Primer escalón del pipeline (regla 7 CLAUDE.md): nada se parsea ni se guarda
en la base sin que el crudo exista antes en MinIO, con su `content_hash`. Es
lo único irreversible del proceso — si el portal cambia después, esto es lo
único que prueba qué decía el día que se leyó.

El cliente de MinIO es un parámetro explícito (`MinioTarget`), no algo que
esta función decide sola: así el mismo código sirve para `local` o
`shared` sin arriesgarse a que uno se quede fijo en el `.env` mientras el
otro cambia por línea de comandos (bug real, 2026-09-08: el RAW subió al
MinIO local aunque los datos se escribieron en la base compartida).
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import structlog
from apps.api.config import get_settings
from minio import Minio
from minio.error import S3Error

log = structlog.stdlib.get_logger("ingestion.snice")


@dataclass(frozen=True)
class RawCapture:
    """Metadata de un archivo crudo ya almacenado en MinIO."""

    source_url: str
    minio_key: str
    content_hash: str
    size_bytes: int
    retrieved_at: datetime


@dataclass(frozen=True)
class MinioTarget:
    """Cliente + bucket de un destino MinIO — local o compartido."""

    client: Minio
    bucket: str


def local_target() -> MinioTarget:
    """El MinIO de tu `.env` — siempre el local, nunca el compartido."""
    settings = get_settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password.get_secret_value(),
        secure=settings.minio_secure,
    )
    return MinioTarget(client=client, bucket=settings.minio_bucket_raw)


def parse_minio_url(url: str) -> tuple[str, str | None, str | None, bool]:
    """`http://usuario:secreto@host:puerto` -> (endpoint, access_key, secret_key, secure).

    Función pura, separada de `shared_target()`, para poder probar el parseo
    sin construir un cliente MinIO de verdad.
    """
    parts = urlsplit(url)
    endpoint = f"{parts.hostname}:{parts.port}" if parts.port else (parts.hostname or "")
    return endpoint, parts.username, parts.password, parts.scheme == "https"


def shared_target() -> MinioTarget:
    """El MinIO compartido del equipo, vía `ADUANERO_SHARED_MINIO_URL`.

    Nunca en el `.env` por default — solo cuando de verdad vas a escribir ahí,
    igual que `ADUANERO_SHARED_URL` para la base (Persona 1, 2026-09-07).
    Formato: `http://usuario:secreto@host:puerto`.
    """
    url = os.environ.get("ADUANERO_SHARED_MINIO_URL")
    if not url:
        raise RuntimeError(
            "ADUANERO_SHARED_MINIO_URL no está definida. Pide las credenciales "
            "de MinIO compartido a Persona 1 por canal seguro y ponlas en tu "
            ".env — nunca en un chat."
        )
    endpoint, access_key, secret_key, secure = parse_minio_url(url)
    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    # Mismo nombre de bucket que el local: solo cambia el destino, no el layout.
    return MinioTarget(client=client, bucket=get_settings().minio_bucket_raw)


def fetch(url: str, *, timeout: float = 60.0) -> bytes:
    """Descarga el archivo tal cual, sin transformarlo."""
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.content


def content_hash(data: bytes) -> str:
    """sha256 del contenido descargado."""
    return hashlib.sha256(data).hexdigest()


def store_raw_bytes(
    data: bytes, *, source_url: str, minio_key: str, target: MinioTarget
) -> RawCapture:
    """Sube bytes ya descargados a `target`. Separado de `store_raw` para no
    descargar la misma fuente dos veces cuando el llamador también necesita
    los bytes para parsear (ver `ingestion.snice.cli`)."""
    digest = content_hash(data)
    if not target.client.bucket_exists(target.bucket):
        raise RuntimeError(f"el bucket {target.bucket!r} no existe en MinIO")

    target.client.put_object(target.bucket, minio_key, io.BytesIO(data), length=len(data))
    retrieved_at = datetime.now(UTC)
    log.info(
        "snice.raw.stored",
        source_url=source_url,
        minio_key=minio_key,
        content_hash=digest,
        size_bytes=len(data),
    )
    return RawCapture(
        source_url=source_url,
        minio_key=minio_key,
        content_hash=digest,
        size_bytes=len(data),
        retrieved_at=retrieved_at,
    )


def store_raw(url: str, minio_key: str, *, target: MinioTarget) -> RawCapture:
    """Descarga `url`, la sube a `target` y devuelve su metadata.

    El bucket tiene versionado (`docker-compose.yml`), así que una nueva
    captura bajo la misma `minio_key` no borra la anterior.
    """
    return store_raw_bytes(fetch(url), source_url=url, minio_key=minio_key, target=target)


def verify_stored(*, target: MinioTarget, minio_key: str) -> None:
    """Confirma que el RAW existe en ESTE destino antes de escribir en su base.

    Sin esto, nada impide subir el RAW a un MinIO y los datos a la base de
    otro — que es exactamente lo que pasó (Persona 1, 2026-09-08): RAW en el
    MinIO local, filas en la base compartida. Un mismatch de destino no debe
    pasar en silencio.
    """
    try:
        target.client.stat_object(target.bucket, minio_key)
    except S3Error as exc:
        raise RuntimeError(
            f"RAW no encontrado en este destino ({target.bucket}/{minio_key}). "
            "No se escribe en la base sin su RAW correspondiente en el mismo "
            "destino (regla 7 CLAUDE.md)."
        ) from exc
