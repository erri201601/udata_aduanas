"""El endpoint que revisa un pedimento completo.

Se prueba sobre todo su capacidad de negarse: sin tasas conocidas no
cuantifica, sin producto ligado no construye espejo, y ninguna de las dos
cosas es un error 500 — son resultados legítimos que hay que persistir.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from apps.api.routers.pedimentos import ReviewRequest, _construir_espejo, _declarada, _tasas
from database.models import Pedimento, PedimentoItem
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

FECHA = date(2026, 3, 15)


def _partida(**kw: Any) -> PedimentoItem:
    base: dict[str, Any] = {
        "line_number": 1,
        "description": "Computadora portátil",
        "declared_fraction_code": "85285900",
        "declared_nico_code": "00",
        "country_of_origin": "CN",
        "customs_value": Decimal("100000.00"),
        "customs_value_currency": "MXN",
        "applied_nom_codes": ["NOM-019-SCFI"],
        "identifiers": {},
        "product_id": None,
    }
    base.update(kw)
    return PedimentoItem(**base)


# ── Lo que se declara se copia, no se interpreta ─────────────────────────────


def test_la_partida_declarada_se_copia_tal_cual() -> None:
    d = _declarada(_partida(), exchange_rate=None)

    assert d.fraction_code == "85285900"
    assert d.applied_nom_codes == ("NOM-019-SCFI",)
    assert d.customs_value == Decimal("100000.00")


def test_una_partida_sin_nom_declaradas_no_falla() -> None:
    assert _declarada(_partida(applied_nom_codes=None), exchange_rate=None).applied_nom_codes == ()


# ── Sin espejo no hay comparación ────────────────────────────────────────────


def test_sin_producto_ligado_se_comprueba_lo_que_no_exige_clasificar() -> None:
    """Antes la partida quedaba sin mirar. Clasificar necesita producto; el
    país, el NICO y la aritmética del valor, no (Persona 1, 21-sep)."""
    catalogo = MagicMock()
    catalogo.nicos.return_value = ("00",)
    # Sin tasa ni catálogo de unidades: lo fiscal y la unidad quedan sin
    # comprobar, que es lo que este test mira — el país y el NICO sí.
    catalogo.igi_rate.return_value = None
    catalogo.hay_unidades.return_value = False
    espejo = _construir_espejo(
        MagicMock(), _partida(product_id=None), FECHA, catalogo, ReviewRequest()
    )

    assert espejo is not None
    assert espejo.is_resolved is False, "no se clasificó nada"
    assert espejo.fraction_code is None
    assert espejo.valid_nico_codes == ("00",)


# ── Las tasas: la regla es no inventarlas ────────────────────────────────────


def _catalogo(declarada: str | None, esperada: str | None) -> MagicMock:
    catalogo = MagicMock()
    catalogo.igi_rate.side_effect = lambda *, on_date, fraction_code: {
        "85285900": Decimal(declarada) if declarada is not None else None,
        "84713001": Decimal(esperada) if esperada is not None else None,
    }.get(fraction_code)
    return catalogo


def test_con_las_dos_tasas_conocidas_se_cuantifica() -> None:
    declaradas, esperadas = _tasas(
        _catalogo("0.15", "0.00"),
        FECHA,
        ReviewRequest(iva_rate=Decimal("0.16"), dta_rate=Decimal("0.008")),
        declarada="85285900",
        esperada="84713001",
    )

    assert declaradas is not None and esperadas is not None
    assert declaradas.igi_rate == Decimal("0.15")
    assert esperadas.igi_rate == Decimal("0.00")
    assert declaradas.iva_rate == esperadas.iva_rate == Decimal("0.16")


@pytest.mark.parametrize(
    ("declarada", "esperada"),
    [(None, "0.00"), ("0.15", None), (None, None)],
)
def test_si_falta_una_tasa_no_se_cuantifica_ninguna(
    declarada: str | None, esperada: str | None
) -> None:
    """EL TEST QUE IMPORTA.

    Cuantificar con una sola tasa daría una diferencia contra cero. Sería un
    número plausible, con dos decimales, y completamente inventado.
    """
    assert _tasas(
        _catalogo(declarada, esperada),
        FECHA,
        ReviewRequest(),
        declarada="85285900",
        esperada="84713001",
    ) == (None, None)


def test_sin_fraccion_esperada_no_se_cuantifica() -> None:
    """Si la clasificación no se sostuvo, no hay contra qué comparar."""
    assert _tasas(
        _catalogo("0.15", "0.00"), FECHA, ReviewRequest(), declarada="85285900", esperada=None
    ) == (None, None)


def test_las_tasas_no_declaradas_valen_cero_no_una_inventada() -> None:
    """Quien no pasa IVA obtiene 0, no el 0.16 «de siempre»: codificarlo aquí
    sería fundamento jurídico inventado."""
    declaradas, _ = _tasas(
        _catalogo("0.15", "0.00"),
        FECHA,
        ReviewRequest(),
        declarada="85285900",
        esperada="84713001",
    )

    assert declaradas is not None
    assert declaradas.iva_rate == Decimal("0")
    assert declaradas.dta_rate == Decimal("0")


# ── Los códigos de error del endpoint ────────────────────────────────────────


class SesionFalsa:
    def __init__(self, pedimento: Pedimento | None, partidas: list[PedimentoItem]) -> None:
        self._pedimento = pedimento
        self._partidas = partidas

    def get(self, _modelo: type, _id: uuid.UUID) -> Any:
        return self._pedimento

    def scalars(self, _sentencia: Any) -> Any:
        resultado = type("R", (), {})()
        resultado.all = lambda: self._partidas
        return resultado


def _cliente(pedimento: Pedimento | None, partidas: list[PedimentoItem]) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(pedimento, partidas)
    return TestClient(app)


def test_pedimento_inexistente_da_404() -> None:
    with _cliente(None, []) as c:
        r = c.post(f"/pedimentos/{uuid.uuid4()}/review", json={})

    assert r.status_code == 404


def test_pedimento_sin_partidas_da_409() -> None:
    """No es un 500: un pedimento sin partidas es un dato malo, no un fallo."""
    pedimento = Pedimento(
        pedimento_number="26 47 3859 6000012",
        trade_flow="IMPORT",
        operation_date=FECHA,
        currency="MXN",
        data_origin="SYNTHETIC",
        is_simulation=True,
    )
    with _cliente(pedimento, []) as c:
        r = c.post(f"/pedimentos/{uuid.uuid4()}/review", json={})

    assert r.status_code == 409
    assert "partidas" in r.json()["detail"]
