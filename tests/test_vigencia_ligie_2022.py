"""La LIGIE 2022 rige desde el 12-dic-2022, no desde su publicación (ADR 0018)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from ingestion.diputados.load import LIGIE_ARTICULO1_VALID_FROM
from ingestion.snice.load import LIGIE_PUBLISHED_AT, LIGIE_VALID_FROM

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit


def test_publicada_el_7_de_junio_y_en_vigor_el_12_de_diciembre() -> None:
    """Cuarta Resolución de Modificaciones a las RGCE 2022, punto SEGUNDO."""
    assert date(2022, 6, 7) == LIGIE_PUBLISHED_AT
    assert date(2022, 12, 12) == LIGIE_VALID_FROM
    assert LIGIE_ARTICULO1_VALID_FROM == LIGIE_VALID_FROM, "es la misma ley"


@pytest.mark.integration
def test_la_correccion_mueve_la_vigencia_sin_tocar_ids_ni_lo_sintetico(
    pg_session: Session,  # noqa: F811
) -> None:
    import sqlalchemy as sa
    from database.models import TariffFraction
    from ingestion.snice.corregir_vigencia import corregir

    sintetica = TariffFraction(
        code="99999999",
        chapter="99",
        heading="9999",
        subheading="999999",
        description="sintética",
        data_origin="SYNTHETIC",
        valid_from=LIGIE_PUBLISHED_AT,
        source_url="https://ejemplo.invalido",
        content_hash="0" * 64,
        retrieved_at=sa.func.now(),
    )
    real = TariffFraction(
        code="99999998",
        chapter="99",
        heading="9999",
        subheading="999999",
        description="oficial",
        data_origin="OFFICIAL",
        valid_from=LIGIE_PUBLISHED_AT,
        source_url="https://ejemplo.invalido",
        content_hash="0" * 64,
        retrieved_at=sa.func.now(),
    )
    pg_session.add_all([sintetica, real])
    pg_session.flush()
    id_real = real.id

    primera = corregir(pg_session)
    segunda = corregir(pg_session)

    assert primera["tariff_fractions"] >= 1
    assert sum(segunda.values()) == 0, "idempotente"
    pg_session.expire_all()
    corregida = pg_session.get(TariffFraction, id_real)
    assert corregida is not None
    assert corregida.valid_from == date(2022, 12, 12)
    assert corregida.published_at == date(2022, 6, 7)
    assert pg_session.get(TariffFraction, sintetica.id).valid_from == LIGIE_PUBLISHED_AT
