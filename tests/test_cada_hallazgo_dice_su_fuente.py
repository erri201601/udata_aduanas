"""Cada hallazgo dice de qué fila sale (§21 `source_ids`).

Hasta el 13-oct, 0 de 315 hallazgos vigentes tenían evidencia enlazada y la
tabla no tenía dónde poner una fuente. Se protege el recorrido: la fuente de
una expectativa llega a su divergencia, de ahí al hallazgo y a la fila.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from core.audit import audit
from core.shadow import DeclaredItem, DivergenceType, ExpectedItem, SourceRef, compare
from schemas.intelligence import RiskFindingRead

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

LIGIE = SourceRef(
    what="fracción 84713001 en la LIGIE",
    table="regulatory.tariff_fractions",
    row_id="fila-1",
    document="LIGIE 2022 (DOF)",
    url="https://www.dof.gob.mx/",
    content_hash="sha256:abc",
    valid_from=date(2022, 6, 7),
    data_origin="OFFICIAL",
)
NOM = SourceRef(what="NOM-001", table="regulatory.fraction_nom_requirements")


def _divergencias() -> list:  # type: ignore[type-arg]
    return list(
        compare(
            [DeclaredItem(line_number=1, fraction_code="85285900")],
            [
                ExpectedItem(
                    line_number=1,
                    fraction_code="84713001",
                    is_resolved=True,
                    confidence=Decimal("1"),
                    required_nom_codes=("NOM-001",),
                    sources={"fraction_code": (LIGIE,), "applied_nom_codes": (NOM,)},
                )
            ],
        ).divergences
    )


@pytest.mark.unit
def test_cada_divergencia_lleva_la_fuente_de_su_campo() -> None:
    por_tipo = {d.kind: d for d in _divergencias()}
    assert por_tipo[DivergenceType.FRACTION_MISMATCH].sources == (LIGIE,)
    assert por_tipo[DivergenceType.MISSING_NOM].sources == (NOM,)


@pytest.mark.unit
def test_un_campo_sin_fuente_no_toma_la_de_otro() -> None:
    [d] = compare(
        [DeclaredItem(line_number=1, country_of_origin="CN")],
        [
            ExpectedItem(
                line_number=1,
                country_of_origin="US",
                sources={"fraction_code": (LIGIE,)},
            )
        ],
    ).divergences
    assert d.sources == ()


@pytest.mark.unit
def test_la_fuente_llega_a_la_fila_del_hallazgo() -> None:
    hallazgos = audit(
        compare_y_nada := compare(
            [DeclaredItem(line_number=1, fraction_code="85285900")],
            [
                ExpectedItem(
                    line_number=1,
                    fraction_code="84713001",
                    is_resolved=True,
                    confidence=Decimal("1"),
                    sources={"fraction_code": (LIGIE,)},
                )
            ],
        )
    ).findings
    assert compare_y_nada.divergences
    [fila] = [h.to_finding_fields()["sources"] for h in hallazgos]
    assert fila == [LIGIE.model_dump(mode="json")]
    assert fila[0]["content_hash"] == "sha256:abc"


@pytest.mark.unit
def test_una_fila_sin_fuentes_se_lee_como_lista_vacia() -> None:
    campos = {
        "id": "00000000-0000-0000-0000-000000000001",
        "created_at": "2026-10-13T00:00:00Z",
        "updated_at": "2026-10-13T00:00:00Z",
        "finding_type": "MISSING_NOM",
        "severity": "HIGH",
        "data_origin": "SYNTHETIC",
        "sources": None,
    }
    assert RiskFindingRead.model_validate(campos).sources == []


@pytest.mark.integration
def test_el_igi_cita_la_fraccion_y_el_articulo_64(pg_session: Session) -> None:  # noqa: F811
    from apps.api.fuentes import fuentes_de_la_partida
    from database.models import Pedimento, PedimentoItem, TariffFraction

    fila = pg_session.execute(
        sa.select(PedimentoItem, Pedimento.operation_date, Pedimento.pedimento_key)
        .join(Pedimento, Pedimento.id == PedimentoItem.pedimento_id)
        .join(TariffFraction, TariffFraction.code == PedimentoItem.declared_fraction_code)
        .where(
            TariffFraction.valid_from <= Pedimento.operation_date,
            sa.or_(
                TariffFraction.valid_to.is_(None),
                TariffFraction.valid_to >= Pedimento.operation_date,
            ),
        )
        .limit(1)
    ).first()
    if fila is None:
        pytest.skip("no hay partidas con fracción vigente en la LIGIE cargada")
    partida, fecha, clave = fila

    fuentes = fuentes_de_la_partida(
        pg_session,
        partida=partida,
        fecha=fecha,
        esperada=ExpectedItem(line_number=partida.line_number, igi_amount=Decimal("1")),
        pedimento_key=clave,
    )

    tablas = {f.table for f in fuentes.get("igi_amount", ())}
    assert "regulatory.tariff_fractions" in tablas
    assert all(f.content_hash and f.url for f in fuentes["igi_amount"])
    if "regulatory.legal_rules" not in tablas:
        pytest.skip("la Ley Aduanera no está cargada")
    assert any("artículo 64" in f.what for f in fuentes["igi_amount"])
