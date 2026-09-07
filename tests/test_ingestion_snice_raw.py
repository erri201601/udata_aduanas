"""Tests de `ingestion.snice.raw`: destino de MinIO y el guardia RAW-antes-que-nada.

`unit` — sin red ni MinIO real: usa un cliente falso que solo implementa lo
que `raw.py` necesita (`bucket_exists`, `put_object`, `stat_object`).
"""

from __future__ import annotations

import io

import pytest
from ingestion.snice import raw
from minio.error import S3Error

pytestmark = pytest.mark.unit


class _ClienteFalso:
    """Imita lo mínimo de `minio.Minio` que usa `raw.py`, sin red."""

    def __init__(self, buckets: set[str] | None = None) -> None:
        self.buckets = buckets if buckets is not None else {"aduanero-raw"}
        self.objects: dict[tuple[str, str], bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def put_object(self, bucket: str, key: str, stream: io.BytesIO, length: int) -> None:
        self.objects[(bucket, key)] = stream.read()

    def stat_object(self, bucket: str, key: str) -> None:
        if (bucket, key) not in self.objects:
            raise S3Error(
                response=None,
                code="NoSuchKey",
                message="no existe",
                resource=key,
                request_id="test",
                host_id="test",
                bucket_name=bucket,
                object_name=key,
            )


def test_parse_minio_url_extrae_endpoint_usuario_secreto_y_esquema() -> None:
    endpoint, access_key, secret_key, secure = raw.parse_minio_url(
        "http://aduanero_minio:s3cr3t@100.86.182.104:9000"
    )

    assert endpoint == "100.86.182.104:9000"
    assert access_key == "aduanero_minio"
    assert secret_key == "s3cr3t"
    assert secure is False


def test_parse_minio_url_reconoce_https_como_seguro() -> None:
    _, _, _, secure = raw.parse_minio_url("https://user:pass@minio.example.com:9000")

    assert secure is True


def test_shared_target_falla_sin_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADUANERO_SHARED_MINIO_URL", raising=False)

    with pytest.raises(RuntimeError, match="ADUANERO_SHARED_MINIO_URL"):
        raw.shared_target()


def test_store_raw_bytes_sube_al_target_indicado() -> None:
    cliente = _ClienteFalso()
    target = raw.MinioTarget(client=cliente, bucket="aduanero-raw")  # type: ignore[arg-type]

    capture = raw.store_raw_bytes(
        b"contenido", source_url="https://x", minio_key="snice/x.xlsx", target=target
    )

    assert cliente.objects[("aduanero-raw", "snice/x.xlsx")] == b"contenido"
    assert capture.content_hash == raw.content_hash(b"contenido")


def test_store_raw_bytes_falla_si_el_bucket_no_existe() -> None:
    cliente = _ClienteFalso(buckets=set())
    target = raw.MinioTarget(client=cliente, bucket="aduanero-raw")  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="bucket"):
        raw.store_raw_bytes(b"x", source_url="https://x", minio_key="k", target=target)


def test_verify_stored_pasa_si_el_objeto_existe() -> None:
    cliente = _ClienteFalso()
    target = raw.MinioTarget(client=cliente, bucket="aduanero-raw")  # type: ignore[arg-type]
    raw.store_raw_bytes(b"x", source_url="https://x", minio_key="snice/x.xlsx", target=target)

    raw.verify_stored(target=target, minio_key="snice/x.xlsx")  # no debe lanzar


def test_verify_stored_falla_si_el_raw_esta_en_otro_destino() -> None:
    """El caso real: RAW subido al MinIO local, intento de verificar contra el compartido."""
    local = raw.MinioTarget(client=_ClienteFalso(), bucket="aduanero-raw")  # type: ignore[arg-type]
    raw.store_raw_bytes(b"x", source_url="https://x", minio_key="snice/x.xlsx", target=local)

    compartido = raw.MinioTarget(client=_ClienteFalso(), bucket="aduanero-raw")  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no encontrado en este destino"):
        raw.verify_stored(target=compartido, minio_key="snice/x.xlsx")
