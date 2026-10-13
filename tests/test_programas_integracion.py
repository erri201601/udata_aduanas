"""`cargar_programas`: vigencia, tasa de la Regla 8ª desde la LIGIE, y `None`
frente a catálogo vacío (ADR 0011).

Contra Postgres, en una transacción que se revierte. Las filas se insertan con
una fecha muy lejana (2099) para no mezclarse con lo que Persona 2 cargue: lo
vigente en esa fecha es sólo lo de este test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from core.opportunity import OpportunityKind
from database.models import ProsecRate, Regla8aFraction
from database.repositories.programas import cargar_programas
from database.repositories.tariff import TariffCatalogRepository

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

FECHA = date(2099, 6, 1)
PROCEDENCIA = {
    "data_origin": "SYNTHETIC",
    "source_url": "https://ejemplo.invalido/prueba",
    "content_hash": "0" * 64,
    "retrieved_at": datetime.now(UTC),
}


class _Catalogo:
    """La tasa de la 9802 sale de la LIGIE; aquí, de un diccionario."""

    def __init__(self, tasas: dict[str, Decimal]) -> None:
        self.tasas = tasas

    def igi_rate(self, *, on_date: date, fraction_code: str) -> Decimal | None:
        return self.tasas.get(fraction_code)


def _catalogo(tasas: dict[str, Decimal]) -> TariffCatalogRepository:
    return _Catalogo(tasas)  # type: ignore[return-value]


def test_sin_filas_vigentes_es_none_no_vacio(pg_session: Session) -> None:  # noqa: F811
    pg_session.add(
        ProsecRate(
            sector_code="I",
            sector_name="Eléctrica",
            fraction_code="85285901",
            igi_rate=Decimal("0"),
            valid_from=date(2098, 1, 1),
            valid_to=date(2098, 12, 31),
            **PROCEDENCIA,
        )
    )
    pg_session.flush()
    assert cargar_programas(pg_session, on_date=FECHA, catalogo=_catalogo({})) is None


def test_lo_vigente_se_reparte_por_fraccion(pg_session: Session) -> None:  # noqa: F811
    pg_session.add_all(
        [
            ProsecRate(
                sector_code="I",
                sector_name="Eléctrica",
                fraction_code="85285901",
                igi_rate=Decimal("0.05"),
                valid_from=date(2099, 1, 1),
                **PROCEDENCIA,
            ),
            ProsecRate(
                sector_code="II",
                sector_name="Electrónica",
                fraction_code="99999999",
                igi_rate=Decimal("0"),
                valid_from=date(2099, 1, 1),
                **PROCEDENCIA,
            ),
            Regla8aFraction(
                sector_code="I",
                sector_name="Eléctrica",
                fraction_code="98029901",
                valid_from=date(2099, 1, 1),
                **PROCEDENCIA,
            ),
            Regla8aFraction(
                sector_code="II",
                sector_name="Electrónica",
                fraction_code="98029902",
                valid_from=date(2099, 1, 1),
                **PROCEDENCIA,
            ),
        ]
    )
    pg_session.flush()

    catalogo = cargar_programas(
        pg_session, on_date=FECHA, catalogo=_catalogo({"98029901": Decimal("0")})
    )

    assert catalogo is not None
    opciones = catalogo.para("85285901")
    assert [(o.kind, o.sector_code) for o in opciones] == [
        (OpportunityKind.PROSEC, "I"),
        (OpportunityKind.REGLA_8A, "I"),
    ], "la 98029902 no tiene tasa en la LIGIE: se omite, no se supone cero"
    assert all(o.data_origin == "SYNTHETIC" for o in opciones)
    assert catalogo.para(None) == ()
