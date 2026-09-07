"""Tests del router de lectura de productos.

Sin PostgreSQL: la sesión se sustituye con `dependency_overrides`, que es
justo para lo que FastAPI la expone. Los tests de integración contra la base
compartida tendrían que acotarse a las filas que ellos mismos crean —la base
ya tiene datos del seed y «cualquier fila que cumpla X» dejó de ser
determinista—, así que aquí se evita el problema de raíz.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import Product, ProductAttribute, ProductDna
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
PRODUCT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DNA_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _con_auditoria(fila: Any) -> Any:
    """Rellena lo que en la base pone el servidor y aquí nadie escribe."""
    fila.id = fila.id or uuid.uuid4()
    fila.created_at = AHORA
    fila.updated_at = AHORA
    return fila


def _producto() -> Product:
    p = Product(
        sku="DEMO-001",
        commercial_name='Laptop Demo 14" 8GB',
        brand="Demo",
        country_of_manufacture="CN",
        data_origin="SYNTHETIC",
    )
    p.id = PRODUCT_ID
    return _con_auditoria(p)


def _dna(*, is_current: bool = True) -> ProductDna:
    d = ProductDna(
        product_id=PRODUCT_ID,
        version=1,
        is_current=is_current,
        input_kinds=["text"],
        summary="Laptop portátil, 14 pulgadas.",
        missing_information=["voltage_v"],
        data_origin="SYNTHETIC",
        requires_human_review=True,
    )
    d.id = DNA_ID
    return _con_auditoria(d)


def _atributos() -> list[ProductAttribute]:
    crudos = [
        ("ram_gb", "8", "GB", "OBSERVED", Decimal("0.9900")),
        ("weight_kg", "1.4", "kg", "EXTRACTED", Decimal("0.9500")),
        ("chassis_material", "aluminio", None, "INFERRED", Decimal("0.5800")),
        ("voltage_v", None, "V", "MISSING", None),
    ]
    filas = []
    for nombre, valor, unidad, estado, conf in crudos:
        a = ProductAttribute(
            product_dna_id=DNA_ID,
            name=nombre,
            value=valor,
            unit=unidad,
            status=estado,
            confidence=conf,
            data_origin="SYNTHETIC",
        )
        filas.append(_con_auditoria(a))
    return filas


class SesionFalsa:
    """Sesión mínima: responde `get()` y `scalars()` con lo que se le dé."""

    def __init__(self, *, producto: Product | None, dna: ProductDna | None) -> None:
        self._producto = producto
        self._dna = dna

    def get(self, modelo: type, _id: uuid.UUID) -> Any:
        return self._producto if modelo is Product else None

    def scalars(self, sentencia: Any) -> Any:
        entidad = sentencia.column_descriptions[0]["entity"]
        resultado = MagicMock()
        if entidad is Product:
            resultado.all.return_value = [self._producto] if self._producto else []
        elif entidad is ProductDna:
            resultado.first.return_value = self._dna
        else:
            resultado.all.return_value = _atributos() if self._dna else []
        return resultado


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    """Cliente con el escenario completo: producto, DNA y cuatro atributos."""
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(producto=_producto(), dna=_dna())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cliente_vacio() -> Iterator[TestClient]:
    """Cliente sin datos: para los 404."""
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(producto=None, dna=None)
    with TestClient(app) as c:
        yield c


# ── Listado ─────────────────────────────────────────────────────────────────


def test_lista_productos(cliente: TestClient) -> None:
    r = cliente.get("/products")

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo[0]["sku"] == "DEMO-001"
    assert cuerpo[0]["data_origin"] == "SYNTHETIC"


def test_el_listado_declara_el_origen_del_dato(cliente: TestClient) -> None:
    """§33: la UI no puede marcar SYNTHETIC si la API no lo dice."""
    assert all("data_origin" in p for p in cliente.get("/products").json())


@pytest.mark.parametrize(("limit", "esperado"), [(0, 422), (201, 422), (1, 200)])
def test_el_limite_esta_acotado(cliente: TestClient, limit: int, esperado: int) -> None:
    """Sin tope, una consulta se convierte en una descarga del catálogo."""
    assert cliente.get(f"/products?limit={limit}").status_code == esperado


# ── Detalle ─────────────────────────────────────────────────────────────────


def test_obtiene_un_producto(cliente: TestClient) -> None:
    r = cliente.get(f"/products/{PRODUCT_ID}")

    assert r.status_code == 200
    assert r.json()["commercial_name"] == 'Laptop Demo 14" 8GB'


def test_producto_inexistente_da_404(cliente_vacio: TestClient) -> None:
    assert cliente_vacio.get(f"/products/{PRODUCT_ID}").status_code == 404


def test_un_id_que_no_es_uuid_da_422(cliente: TestClient) -> None:
    assert cliente.get("/products/no-es-un-uuid").status_code == 422


# ── Product DNA ─────────────────────────────────────────────────────────────


def test_el_dna_llega_con_sus_atributos(cliente: TestClient) -> None:
    """Van juntos: un DNA sin atributos no dice nada."""
    r = cliente.get(f"/products/{PRODUCT_ID}/dna")

    assert r.status_code == 200
    assert len(r.json()["attributes"]) == 4


def test_los_cuatro_estados_llegan_al_cliente(cliente: TestClient) -> None:
    """Es lo que la pantalla tiene que poder distinguir (§16)."""
    atributos = cliente.get(f"/products/{PRODUCT_ID}/dna").json()["attributes"]
    estados = {a["status"] for a in atributos}

    assert estados == {"OBSERVED", "EXTRACTED", "INFERRED", "MISSING"}


def test_el_inferido_viaja_con_su_confianza(cliente: TestClient) -> None:
    """Sin confianza, un dato deducido se pinta igual que uno leído."""
    atributos = cliente.get(f"/products/{PRODUCT_ID}/dna").json()["attributes"]
    inferido = next(a for a in atributos if a["status"] == "INFERRED")

    assert Decimal(str(inferido["confidence"])) == Decimal("0.5800")


def test_el_faltante_llega_sin_valor(cliente: TestClient) -> None:
    """Un dato ausente no puede aparecer relleno al otro lado de la API."""
    atributos = cliente.get(f"/products/{PRODUCT_ID}/dna").json()["attributes"]
    faltante = next(a for a in atributos if a["status"] == "MISSING")

    assert faltante["value"] is None
    assert faltante["confidence"] is None


def test_el_dna_declara_lo_que_falta(cliente: TestClient) -> None:
    """`missing_information` dispara la petición al importador (§16)."""
    assert cliente.get(f"/products/{PRODUCT_ID}/dna").json()["missing_information"] == ["voltage_v"]


def test_sin_dna_vigente_da_404(cliente_vacio: TestClient) -> None:
    assert cliente_vacio.get(f"/products/{PRODUCT_ID}/dna").status_code == 404
