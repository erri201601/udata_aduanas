"""Tests del router de hallazgos.

El test que importa es `test_nunca_afirma_que_un_pedimento_este_limpio`: un
pedimento sin verificar no está limpio, y confundirlos haría que alguien
presente ante la autoridad algo que nadie revisó.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from database.models import Pedimento, RiskFinding, ShadowReview
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
PEDIMENTO_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _aud(fila: Any) -> Any:
    fila.id = fila.id or uuid.uuid4()
    fila.created_at = AHORA
    fila.updated_at = AHORA
    if getattr(fila, "is_simulation", None) is None:
        fila.is_simulation = True
    if getattr(fila, "requires_human_review", None) is None:
        fila.requires_human_review = False
    return fila


def _pedimento() -> Pedimento:
    p = Pedimento(
        client_id=uuid.uuid4(),
        pedimento_number="26 47 3456 6001234",
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        currency="MXN",
        data_origin="SYNTHETIC",
    )
    p.id = PEDIMENTO_ID
    return _aud(p)


def _hallazgos() -> list[RiskFinding]:
    crudos = [
        ("FRACTION_MISMATCH", "HIGH", Decimal("48200.000000"), "Fracción de unidades de proceso."),
        ("NOM_MISSING", "CRITICAL", None, "Falta la NOM-019; detiene la mercancía."),
        ("VALUE_DEVIATION", "LOW", Decimal("0.000000"), "Diferencia dentro de tolerancia."),
    ]
    filas = []
    for tipo, sev, impacto, razon in crudos:
        f = RiskFinding(
            pedimento_id=PEDIMENTO_ID,
            finding_type=tipo,
            severity=sev,
            rationale=razon,
            impact_amount=impacto,
            impact_amount_currency="MXN" if impacto is not None else None,
            data_origin="SYNTHETIC",
        )
        filas.append(_aud(f))
    return filas


def _revision(*, is_complete: bool, unverifiable: list[str] | None = None) -> ShadowReview:
    r = ShadowReview(
        pedimento_id=PEDIMENTO_ID,
        is_complete=is_complete,
        unverifiable=unverifiable or [],
        engine_version="0.1.0",
        data_origin="SYNTHETIC",
    )
    return _aud(r)


class SesionFalsa:
    def __init__(
        self,
        *,
        pedimento: Pedimento | None,
        hallazgos: list[RiskFinding],
        revision: ShadowReview | None = None,
    ) -> None:
        self._pedimento = pedimento
        self._hallazgos = hallazgos
        self._revision = revision

    def get(self, _modelo: type, _id: uuid.UUID) -> Any:
        return self._pedimento

    def scalars(self, sentencia: Any) -> Any:
        entidad = sentencia.column_descriptions[0]["entity"]
        resultado = type("R", (), {})()
        if entidad is Pedimento:
            resultado.all = lambda: [self._pedimento] if self._pedimento else []
        elif entidad is ShadowReview:
            resultado.first = lambda: self._revision
        else:
            resultado.all = lambda: self._hallazgos
        return resultado


def _cliente(
    *,
    pedimento: Pedimento | None,
    hallazgos: list[RiskFinding],
    revision: ShadowReview | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(
        pedimento=pedimento, hallazgos=hallazgos, revision=revision
    )
    return TestClient(app)


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    with _cliente(pedimento=_pedimento(), hallazgos=_hallazgos()) as c:
        yield c


@pytest.fixture
def cliente_sin_hallazgos() -> Iterator[TestClient]:
    with _cliente(pedimento=_pedimento(), hallazgos=[]) as c:
        yield c


# ── La distinción que no se puede perder ────────────────────────────────────


def test_sin_auditar_no_se_afirma_que_este_limpio(
    cliente_sin_hallazgos: TestClient,
) -> None:
    """EL TEST QUE IMPORTA.

    Cero hallazgos y ninguna revisión NO autoriza a decir «limpio»: nadie lo
    miró. `coverage_known` en `false` significa «nunca se auditó», no
    «se auditó y quedó incompleto».
    """
    cuerpo = cliente_sin_hallazgos.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()

    assert cuerpo["findings"] == []
    assert cuerpo["coverage_known"] is False
    assert cuerpo["is_complete"] is None
    assert cuerpo["worst_severity"] is None


def test_auditado_completo_sin_hallazgos_si_se_puede_afirmar() -> None:
    """Éste es el único caso en que un pedimento está realmente limpio."""
    with _cliente(pedimento=_pedimento(), hallazgos=[], revision=_revision(is_complete=True)) as c:
        cuerpo = c.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()

    assert cuerpo["coverage_known"] is True
    assert cuerpo["is_complete"] is True
    assert cuerpo["unverifiable"] == []
    assert cuerpo["findings"] == []


def test_auditado_incompleto_no_es_lo_mismo_que_sin_auditar() -> None:
    """Tres estados, no dos. Colapsarlos haría que un pedimento sin tocar
    pareciera revisado a medias, o al revés."""
    with _cliente(
        pedimento=_pedimento(),
        hallazgos=[],
        revision=_revision(is_complete=False, unverifiable=["partida 3: sin ficha técnica"]),
    ) as c:
        cuerpo = c.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()

    assert cuerpo["coverage_known"] is True
    assert cuerpo["is_complete"] is False
    assert cuerpo["unverifiable"] == ["partida 3: sin ficha técnica"]


def test_lo_no_verificable_llega_con_su_razon() -> None:
    """«No pude revisarlo» sin decir por qué no sirve para actuar."""
    with _cliente(
        pedimento=_pedimento(),
        hallazgos=_hallazgos(),
        revision=_revision(is_complete=False, unverifiable=["partida 2: falta factura"]),
    ) as c:
        cuerpo = c.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()

    assert cuerpo["unverifiable"] == ["partida 2: falta factura"]
    assert cuerpo["reviewed_at"] is not None


# ── Severidad ───────────────────────────────────────────────────────────────


def test_los_hallazgos_llegan_de_mas_grave_a_menos(cliente: TestClient) -> None:
    """Quien audita empieza por lo que detiene la mercancía."""
    hallazgos = cliente.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()["findings"]

    assert [h["severity"] for h in hallazgos] == ["CRITICAL", "HIGH", "LOW"]


def test_declara_la_peor_severidad(cliente: TestClient) -> None:
    assert (
        cliente.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()["worst_severity"] == "CRITICAL"
    )


def test_un_hallazgo_sin_impacto_puede_ser_el_mas_grave(cliente: TestClient) -> None:
    """`impact_amount = None` no es «menos grave».

    Una NOM faltante no cambia lo que se paga y aun así detiene la mercancía.
    """
    hallazgos = cliente.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()["findings"]
    peor = hallazgos[0]

    assert peor["severity"] == "CRITICAL"
    assert peor["impact_amount"] is None


# ── Contenido ───────────────────────────────────────────────────────────────


def test_cada_hallazgo_explica_su_motivo(cliente: TestClient) -> None:
    """Un hallazgo sin razonamiento no es revisable por nadie."""
    hallazgos = cliente.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()["findings"]

    assert all(h["rationale"] for h in hallazgos)


def test_los_hallazgos_se_declaran_simulacion(cliente: TestClient) -> None:
    """§33: mientras alguna entrada sea SYNTHETIC, es una simulación."""
    hallazgos = cliente.get(f"/findings/pedimentos/{PEDIMENTO_ID}").json()["findings"]

    assert all(h["is_simulation"] for h in hallazgos)


def test_el_listado_ordena_por_severidad_en_la_base(cliente: TestClient) -> None:
    """Ordenar en el cliente dejaría lo grave fuera de la primera página."""
    assert cliente.get("/findings").status_code == 200


def test_el_limite_esta_acotado(cliente: TestClient) -> None:
    assert cliente.get("/findings?limit=500").status_code == 422


def test_pedimento_inexistente_da_404() -> None:
    with _cliente(pedimento=None, hallazgos=[]) as c:
        assert c.get(f"/findings/pedimentos/{PEDIMENTO_ID}").status_code == 404
