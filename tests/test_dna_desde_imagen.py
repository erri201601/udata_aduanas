"""El Product DNA extraído de una imagen (§16 y §48, primer eslabón).

EL TEST QUE IMPORTA es `test_el_crudo_se_guarda_antes_de_mirar_la_imagen`: si
el orden se invirtiera, un fallo del proveedor dejaría atributos sin documento
del que dijeran venir — exactamente lo que el pipeline del §12 existe para
impedir.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from core.llm.errors import ProviderResponseError
from core.product_dna.types import ExtractedAttribute, ProductDnaDraft
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

PRODUCTO = uuid.UUID("77777777-7777-7777-7777-777777777777")
UN_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class _Producto:
    id = PRODUCTO
    data_origin = "SYNTHETIC"


#: Singleton porque `ruff` (B008) prohíbe construirlo en el valor por defecto,
#: y con razón: un objeto creado una vez en la firma se comparte entre
#: llamadas sin que se note.
UN_PRODUCTO = _Producto()


class SesionFalsa:
    def __init__(self, *, producto: Any = UN_PRODUCTO) -> None:
        self._producto = producto
        self.agregadas: list[Any] = []
        self.commits = 0

    def get(self, _modelo: type, _id: uuid.UUID) -> Any:
        return self._producto

    def scalar(self, _sentencia: Any) -> Any:
        return 1  # ya había una versión

    def execute(self, _sentencia: Any) -> Any:
        return None

    def add(self, fila: Any) -> None:
        fila.id = getattr(fila, "id", None) or uuid.uuid4()
        self.agregadas.append(fila)

    def flush(self) -> None: ...

    def commit(self) -> None:
        self.commits += 1


class _Captura:
    minio_key = "product-dna/77777777/abc123"
    content_hash = "abc123"


def _borrador() -> ProductDnaDraft:
    return ProductDnaDraft(
        attributes=(
            ExtractedAttribute(name="material", value="acero inoxidable", status="EXTRACTED"),
        ),
        summary="Sartén de acero inoxidable.",
        missing_information=("diametro_cm",),
        input_kinds=("image",),
    )


class _ExtractorFalso:
    """Registra si le llamaron, para poder afirmar el ORDEN."""

    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.last_metadata = None

    def extract(self, _documento: Any) -> ProductDnaDraft:
        _ExtractorFalso.llamado = True
        return _borrador()


class _ExtractorQueRevienta(_ExtractorFalso):
    def extract(self, _documento: Any) -> ProductDnaDraft:
        raise ProviderResponseError("el modelo devolvió algo ilegible")


def _cliente(monkeypatch: pytest.MonkeyPatch, *, extractor: type = _ExtractorFalso) -> TestClient:
    from apps.api.routers import products

    guardados: list[bytes] = []

    def _guardar(datos: bytes, **_k: Any) -> Any:
        guardados.append(datos)
        return _Captura()

    monkeypatch.setattr(products, "store_raw_bytes", _guardar)
    monkeypatch.setattr(products, "content_hash", lambda _d: "abc123")
    monkeypatch.setattr(products, "local_target", lambda: None)
    monkeypatch.setattr(products, "get_default_provider", lambda: object())
    monkeypatch.setattr(products, "VisionExtractor", extractor)
    monkeypatch.setattr(products, "guardar_dna", _guardar_dna_falso)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa()
    cliente = TestClient(app)
    cliente.guardados = guardados  # type: ignore[attr-defined]
    return cliente


class _DnaFalso:
    id = uuid.uuid4()
    version = 2


def _guardar_dna_falso(*_a: Any, **_k: Any) -> Any:
    return _DnaFalso()


def _subir(cliente: TestClient, *, datos: bytes = UN_PNG, tipo: str = "image/png") -> Any:
    return cliente.post(
        f"/products/{PRODUCTO}/dna/from-image",
        files={"imagen": ("sarten.png", datos, tipo)},
    )


# ── Lo que importa ──────────────────────────────────────────────────────────


def test_el_crudo_se_guarda_antes_de_mirar_la_imagen(monkeypatch: pytest.MonkeyPatch) -> None:
    """EL TEST QUE IMPORTA (§12, regla 7: nunca saltarse RAW).

    Si el proveedor falla, la imagen TIENE que existir igualmente en MinIO con
    su hash. Al revés, un atributo podría acabar en la base sin documento del
    que dijera venir, que es la situación que el pipeline existe para impedir.
    """
    cliente = _cliente(monkeypatch, extractor=_ExtractorQueRevienta)

    with cliente as c:
        r = _subir(c)

    assert r.status_code == 502, "el fallo del proveedor se dice, no se disfraza"
    assert c.guardados == [UN_PNG], "y el crudo quedó guardado igual"  # type: ignore[attr-defined]


def test_extrae_y_devuelve_donde_quedo_el_crudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin `minio_key` y `content_hash` no se puede volver a la imagen.

    Y volver a ella es lo único que prueba, meses después, que el atributo
    salió de esa foto y no de otra.
    """
    cliente = _cliente(monkeypatch)

    with cliente as c:
        r = _subir(c)

    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["minio_key"] == "product-dna/77777777/abc123"
    assert cuerpo["content_hash"] == "abc123"
    assert cuerpo["atributos"] == 1
    assert cuerpo["missing_information"] == ["diametro_cm"]


# ── Lo que se rechaza ───────────────────────────────────────────────────────


def test_un_formato_que_el_proveedor_no_acepta_se_rechaza_antes_de_subir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un PDF hay que rasterizarlo antes; no se sube para que falle después."""
    cliente = _cliente(monkeypatch)

    with cliente as c:
        r = _subir(c, tipo="application/pdf")

    assert r.status_code == 415
    assert c.guardados == [], "ni se subió"  # type: ignore[attr-defined]


def test_una_imagen_vacia_no_pasa(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _cliente(monkeypatch)

    with cliente as c:
        r = _subir(c, datos=b"")

    assert r.status_code == 400


def test_una_imagen_enorme_no_pasa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Más de 8 MB casi nunca es una foto de producto, y el proveedor la
    rechazaría después de habernos costado el viaje."""
    cliente = _cliente(monkeypatch)

    with cliente as c:
        r = _subir(c, datos=b"x" * (8 * 1024 * 1024 + 1))

    assert r.status_code == 413
    assert c.guardados == []  # type: ignore[attr-defined]


def test_un_producto_que_no_existe_da_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.routers import products

    monkeypatch.setattr(products, "store_raw_bytes", lambda *a, **k: _Captura())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(producto=None)

    with TestClient(app) as c:
        r = _subir(c)

    assert r.status_code == 404
