"""Captura RAW de las fuentes SNICE (LIGIE/TIGIE, NICO) a MinIO.

Primer escalón del pipeline (regla 7 CLAUDE.md): nada se parsea ni se guarda
en la base sin que el crudo exista antes en MinIO, con su `content_hash`. Es
lo único irreversible del proceso — si el portal cambia después, esto es lo
único que prueba qué decía el día que se leyó.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import structlog
from apps.api.config import get_settings
from minio import Minio

log = structlog.stdlib.get_logger("ingestion.snice")


@dataclass(frozen=True)
class RawCapture:
    """Metadata de un archivo crudo ya almacenado en MinIO."""

    source_url: str
    minio_key: str
    content_hash: str
    size_bytes: int
    retrieved_at: datetime


def fetch(url: str, *, timeout: float = 60.0) -> bytes:
    """Descarga el archivo tal cual, sin transformarlo."""
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.content


def content_hash(data: bytes) -> str:
    """sha256 del contenido descargado."""
    return hashlib.sha256(data).hexdigest()


def _client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password.get_secret_value(),
        secure=settings.minio_secure,
    )


def store_raw_bytes(data: bytes, *, source_url: str, minio_key: str) -> RawCapture:
    """Sube bytes ya descargados a MinIO. Separado de `store_raw` para no
    descargar la misma fuente dos veces cuando el llamador también necesita
    los bytes para parsear (ver `ingestion.snice.cli`)."""
    digest = content_hash(data)
    settings = get_settings()
    client = _client()
    if not client.bucket_exists(settings.minio_bucket_raw):
        raise RuntimeError(f"el bucket {settings.minio_bucket_raw!r} no existe en MinIO")

    client.put_object(settings.minio_bucket_raw, minio_key, io.BytesIO(data), length=len(data))
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


def store_raw(url: str, minio_key: str) -> RawCapture:
    """Descarga `url`, la sube a MinIO (bucket RAW) y devuelve su metadata.

    El bucket tiene versionado (`docker-compose.yml`), así que una nueva
    captura bajo la misma `minio_key` no borra la anterior.
    """
    return store_raw_bytes(fetch(url), source_url=url, minio_key=minio_key)
