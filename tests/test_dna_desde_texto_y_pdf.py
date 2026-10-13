"""Product DNA desde texto pegado y desde PDF (§16, §48: «ficha técnica + imagen»).

Los dobles —sesión, captura de MinIO, `guardar_dna`— son los del test de la
imagen: las tres entradas comparten el mismo camino a partir del crudo.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from core.llm.errors import ProviderResponseError
from fastapi.testclient import TestClient

from tests.test_dna_desde_imagen import (
    GUARDADO,
    PRODUCTO,
    SesionFalsa,
    _borrador,
    _Captura,
    _guardar_dna_falso,
)
from tests.test_product_dna_pdf import pdf_de_prueba

pytestmark = pytest.mark.unit

FICHA = "Cable de acero galvanizado, construcción 6x36, alma de acero, diámetro 10 mm."


class _Metadata:
    model_provider = "fake"
    model_name = "fake-1"
    prompt_id = "product_dna.extract"
    prompt_version = "0.2"


class _ExtractorDeTexto:
    """Guarda el documento que recibió y deja metadata, como el de verdad."""

    recibido: Any = None

    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.last_metadata = _Metadata()

    def extract(self, documento: Any) -> Any:
        _ExtractorDeTexto.recibido = documento
        return _borrador()


class _ExtractorQueRevienta(_ExtractorDeTexto):
    def extract(self, documento: Any) -> Any:
        raise ProviderResponseError("ilegible")


def _cliente(monkeypatch: pytest.MonkeyPatch, *, extractor: type = _ExtractorDeTexto) -> Any:
    from apps.api.routers import products

    guardados: list[bytes] = []

    def _guardar(datos: bytes, **_k: Any) -> Any:
        guardados.append(datos)
        return _Captura()

    monkeypatch.setattr(products, "store_raw_bytes", _guardar)
    monkeypatch.setattr(products, "content_hash", lambda _d: "abc123")
    monkeypatch.setattr(products, "local_target", lambda: None)
    monkeypatch.setattr(products, "get_default_provider", lambda: object())
    monkeypatch.setattr(products, "LlmExtractor", extractor)
    monkeypatch.setattr(products, "guardar_dna", _guardar_dna_falso)
    _ExtractorDeTexto.recibido = None
    GUARDADO.clear()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa()
    cliente = TestClient(app)
    cliente.guardados = guardados  # type: ignore[attr-defined]
    return cliente


def _pdf(c: TestClient, datos: bytes, nombre: str = "ficha.pdf") -> Any:
    return c.post(
        f"/products/{PRODUCTO}/dna/from-pdf",
        files={"pdf": (nombre, datos, "application/pdf")},
    )


# ── Texto pegado ────────────────────────────────────────────────────────────


def test_el_texto_pegado_tambien_se_guarda_crudo_antes_de_leerlo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Es el documento del que dirán venir los atributos: sin su hash nadie
    podría comprobar después qué se pegó."""
    with _cliente(monkeypatch, extractor=_ExtractorQueRevienta) as c:
        r = c.post(f"/products/{PRODUCTO}/dna/from-text", json={"texto": FICHA})

    assert r.status_code == 502
    assert c.guardados == [FICHA.encode("utf-8")]  # type: ignore[attr-defined]


def test_el_texto_llega_al_extractor_como_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    with _cliente(monkeypatch) as c:
        r = c.post(f"/products/{PRODUCTO}/dna/from-text", json={"texto": FICHA})

    assert r.status_code == 201
    assert _ExtractorDeTexto.recibido.text == FICHA
    assert _ExtractorDeTexto.recibido.kind == "text"


def test_un_texto_demasiado_corto_no_describe_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    with _cliente(monkeypatch) as c:
        r = c.post(f"/products/{PRODUCTO}/dna/from-text", json={"texto": "cable"})

    assert r.status_code == 422
    assert c.guardados == []  # type: ignore[attr-defined]


# ── PDF ─────────────────────────────────────────────────────────────────────


def test_el_pdf_llega_al_modelo_con_sus_paginas_marcadas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Para que pueda decir en qué página encontró cada dato."""
    with _cliente(monkeypatch) as c:
        r = _pdf(c, pdf_de_prueba(["Cable 6x36", "Diametro 10 mm"]))

    assert r.status_code == 201
    documento = _ExtractorDeTexto.recibido
    assert documento.kind == "pdf"
    assert documento.text.startswith("[p.1]\nCable 6x36")
    assert "[p.2]\nDiametro 10 mm" in documento.text


def test_el_pdf_se_guarda_crudo_antes_de_leerlo(monkeypatch: pytest.MonkeyPatch) -> None:
    datos = pdf_de_prueba(["Cable 6x36"])
    with _cliente(monkeypatch, extractor=_ExtractorQueRevienta) as c:
        r = _pdf(c, datos)

    assert r.status_code == 502
    assert c.guardados == [datos]  # type: ignore[attr-defined]


def test_un_escaneo_dice_sin_texto_extraible_y_no_guarda_ficha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin OCR no hay lectura: se dice, y no se guarda una ficha vacía. El crudo
    sí, porque se subió y consta."""
    datos = pdf_de_prueba([None, None])
    with _cliente(monkeypatch) as c:
        r = _pdf(c, datos)

    assert r.status_code == 422
    assert "sin texto extraíble" in r.json()["detail"]
    assert c.guardados == [datos]  # type: ignore[attr-defined]
    assert _ExtractorDeTexto.recibido is None, "no se le pidió nada al modelo"
    assert GUARDADO == {}, "y no se guardó ninguna ficha"


def test_un_archivo_que_no_es_pdf_se_rechaza_antes_de_subir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Por la firma, no por la extensión: un .pdf renombrado no es un PDF."""
    with _cliente(monkeypatch) as c:
        r = _pdf(c, b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    assert r.status_code == 415
    assert c.guardados == []  # type: ignore[attr-defined]


def test_un_pdf_vacio_no_pasa(monkeypatch: pytest.MonkeyPatch) -> None:
    with _cliente(monkeypatch) as c:
        r = _pdf(c, b"")

    assert r.status_code == 400


# ── La evidencia ────────────────────────────────────────────────────────────


def test_la_evidencia_lleva_el_hash_y_la_clave_del_crudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """MODEL_OUTPUT con el `content_hash` y la clave de MinIO en `document_refs`
    (Persona 1, 13-oct): es lo que permite volver al archivo exacto."""
    with _cliente(monkeypatch) as c:
        _pdf(c, pdf_de_prueba(["Cable 6x36"]), nombre="datasheet.pdf")

    evidencia = GUARDADO["evidencia"]
    assert evidencia.kind.value == "MODEL_OUTPUT"
    assert evidencia.prompt_id == "product_dna.extract"
    assert evidencia.content_hash == "abc123"
    campos = evidencia.to_record_fields()
    assert campos["document_refs"] == [
        {
            "document": "PDF subido: datasheet.pdf",
            "url": "product-dna/77777777/abc123",
            "content_hash": "abc123",
        }
    ]
    assert evidencia.is_legal_basis is False, "describe la mercancía, no fundamenta nada"
