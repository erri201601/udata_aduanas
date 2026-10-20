"""Casos comparables en la clasificación (ADR 0019).

Lo que se protege: el extracto es texto literal y no se corta en «Model no.»,
el aviso de «no fundamento» viaja siempre, sin fracción no hay comparables y
las revocadas van después de las vigentes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from database.repositories.comparables import LARGO_EXTRACTO, criterio_de

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

NY = (
    "N342980\n\nFACTS:\n\nThe item is a bird feeder made of steel and plastic.\n\n"
    "The applicable subheading for the Hybird Bird Feeder S9 Series, Model no. BF-1 will be "
    "7323.93.0080, HTSUS, which provides for household articles of stainless steel.\n"
)
HQ = (
    "HQ 958986\n\nHOLDING:\n\nUnder the authority of GRI 1, wire rope with becket loops is "
    "provided for in heading 7312. It is classifiable in subheading 7312.10.90, HTSUS.\n\nSincerely,"
)


def test_la_frase_de_la_subpartida_no_se_corta_en_una_abreviatura() -> None:
    extracto, origen = criterio_de(NY)
    assert origen == "subpartida"
    assert "Model no. BF-1 will be 7323.93.0080" in extracto


def test_sin_frase_de_subpartida_va_el_resolutivo() -> None:
    extracto, origen = criterio_de(HQ)
    assert origen == "holding"
    assert extracto.startswith("Under the authority of GRI 1")
    assert "Sincerely" not in extracto


def test_sin_nada_mejor_van_los_hechos_y_nunca_mas_largo_de_la_cuenta() -> None:
    extracto, origen = criterio_de("FACTS:\n\n" + "palabra " * 200)
    assert origen == "hechos"
    assert len(extracto) <= LARGO_EXTRACTO + 2


def test_el_extracto_es_literal() -> None:
    extracto, _ = criterio_de(NY)
    assert extracto in " ".join(NY.split())


@pytest.mark.integration
def test_el_endpoint_da_la_subpartida_el_aviso_y_las_vigentes_primero(
    pg_session: Session,  # noqa: F811
) -> None:
    from apps.api.routers.classifications import AVISO_COMPARABLES, comparables
    from database.models import ClassificationDecision, ComparableRuling

    def resolucion(numero: str, fecha: date, revocada: bool) -> ComparableRuling:
        return ComparableRuling(
            authority="CBP",
            ruling_number=numero,
            ruling_date=fecha,
            subject=f"prueba {numero}",
            tariff_codes=["9999.98.0010"],
            hs6_codes=["999998"],
            full_text=f"HOLDING:\n\nUnder GRI 1 it is classifiable in 9999.98 ({numero}).\n",
            is_revoked=revocada,
            revoked_by=["X1"] if revocada else [],
            data_origin="PUBLIC",
            valid_from=fecha,
            source_url=f"https://rulings.cbp.gov/ruling/{numero}",
            content_hash="0" * 64,
            retrieved_at=datetime.now(UTC),
        )

    pg_session.add_all(
        [
            resolucion("PRUEBA-REV", date(2025, 1, 1), True),
            resolucion("PRUEBA-NUEVA", date(2024, 1, 1), False),
            resolucion("PRUEBA-VIEJA", date(2001, 1, 1), False),
        ]
    )
    con = ClassificationDecision(
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="RESOLVED",
        fraction_code="99999801",
        engine_version="0.1.0",
        requires_human_review=False,
        data_origin="SYNTHETIC",
    )
    sin = ClassificationDecision(
        trade_flow="IMPORT",
        operation_date=date(2026, 3, 15),
        status="HUMAN_REVIEW_REQUIRED",
        engine_version="0.1.0",
        requires_human_review=True,
        data_origin="SYNTHETIC",
    )
    pg_session.add_all([con, sin])
    pg_session.flush()

    r = comparables(con.id, pg_session, limite=8)
    assert r.hs6 == "999998" and r.total == 3
    assert [c.ruling_number for c in r.comparables] == [
        "PRUEBA-NUEVA",
        "PRUEBA-VIEJA",
        "PRUEBA-REV",
    ]
    assert r.aviso == AVISO_COMPARABLES and "no fundamento" in r.aviso
    assert r.comparables[0].extracto_de == "holding"

    vacio = comparables(sin.id, pg_session, limite=8)
    assert vacio.hs6 is None and vacio.comparables == []

    with pytest.raises(Exception, match="no encontrada"):
        comparables(uuid.uuid4(), pg_session, limite=8)
