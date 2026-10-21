"""Aplicar un decreto que modifica la Tarifa (ADR 0023)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from ingestion.dof.decretos_tarifa import TasaDecretada, aplicar, tasas_del_decreto

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

DECRETO = """<table><tr><td>9803.00.01</td><td>Partes y componentes…</td><td>Kg</td>
<td>Ex.</td><td>Ex.</td></tr><tr><td>7323.93.05</td><td>De acero inoxidable.</td><td>Kg</td>
<td>35</td><td>Ex.</td></tr></table>
<table><tr><td>7208.39.01</td><td>De espesor inferior a 3 mm.</td><td>Ex.</td><td></td></tr></table>"""


def test_lee_las_tasas_y_deja_fuera_las_tablas_del_prosec() -> None:
    tasas = {t.codigo: t for t in tasas_del_decreto(DECRETO)}
    assert set(tasas) == {"98030001", "73239305"}, "la de cuatro columnas es del PROSEC"
    assert tasas["98030001"].igi == Decimal(0)
    assert tasas["73239305"].igi == Decimal("0.35")


@pytest.mark.integration
def test_versiona_sólo_lo_que_cambia_y_se_lleva_los_nico(pg_session: Session) -> None:  # noqa: F811
    import sqlalchemy as sa
    from database.models import Nico, TariffFraction

    comun = {
        "data_origin": "OFFICIAL",
        "source_url": "https://ejemplo.invalido",
        "content_hash": "0" * 64,
        "retrieved_at": datetime.now(UTC),
    }
    f = TariffFraction(
        code="99999901",
        chapter="99",
        heading="9999",
        subheading="999999",
        description="prueba",
        unit="Kg",
        igi_rate=Decimal("0.10"),
        ige_rate=Decimal(0),
        valid_from=date(2022, 12, 12),
        **comun,
    )
    pg_session.add(f)
    pg_session.flush()
    pg_session.add(
        Nico(
            tariff_fraction_id=f.id,
            code="00",
            full_code="9999990100",
            description="Única.",
            valid_from=date(2022, 12, 12),
            **comun,
        )
    )
    pg_session.flush()

    def correr() -> object:
        return aplicar(
            pg_session,
            [TasaDecretada("99999901", Decimal(0), Decimal(0))],
            desde=date(2026, 10, 14),
            hasta=date(2031, 10, 13),
            source_url="https://dof.gob.mx/x",
            source_document="prueba",
            content_hash="1" * 64,
            publicado=date(2026, 10, 13),
        )

    r = correr()
    assert r.cambiadas == ["99999901"]
    assert correr().cambiadas == [], "idempotente: la versión nueva ya tiene esas tasas"
    versiones = pg_session.scalars(
        sa.select(TariffFraction)
        .where(TariffFraction.code == "99999901")
        .order_by(TariffFraction.valid_from)
    ).all()
    assert [(v.valid_from, v.valid_to, v.igi_rate) for v in versiones] == [
        (date(2022, 12, 12), date(2026, 10, 13), Decimal("0.100000")),
        (date(2026, 10, 14), date(2031, 10, 13), Decimal(0)),
    ]
    nicos = pg_session.scalars(
        sa.select(Nico).where(Nico.full_code == "9999990100").order_by(Nico.valid_from)
    ).all()
    assert [(n.tariff_fraction_id, n.valid_to) for n in nicos] == [
        (versiones[0].id, date(2026, 10, 13)),
        (versiones[1].id, date(2031, 10, 13)),
    ]


@pytest.mark.integration
def test_hacia_atras_la_tasa_vale_desde_el_decreto_y_antes_no_se_sabe(
    pg_session: Session,  # noqa: F811
) -> None:
    import sqlalchemy as sa
    from database.models import Nico, TariffFraction
    from ingestion.dof.decretos_tarifa import acotar_hacia_atras

    comun = {
        "data_origin": "OFFICIAL",
        "source_url": "https://ejemplo.invalido",
        "content_hash": "0" * 64,
        "retrieved_at": datetime.now(UTC),
    }
    for codigo, tasa in (("99999911", "0.35"), ("99999912", "0.20")):
        f = TariffFraction(
            code=codigo,
            chapter="99",
            heading="9999",
            subheading="999999",
            description="prueba",
            unit="Kg",
            igi_rate=Decimal(tasa),
            ige_rate=Decimal(0),
            valid_from=date(2022, 12, 12),
            **comun,
        )
        pg_session.add(f)
        pg_session.flush()
        pg_session.add(
            Nico(
                tariff_fraction_id=f.id,
                code="00",
                full_code=f"{codigo}00",
                description="Única.",
                valid_from=date(2022, 12, 12),
                **comun,
            )
        )
    pg_session.flush()

    def acotar(desde: date, tasas: list[TasaDecretada]) -> object:
        return acotar_hacia_atras(
            pg_session,
            tasas,
            desde=desde,
            source_url="https://dof.gob.mx/x",
            source_document="prueba",
            content_hash="1" * 64,
            publicado=desde,
        )

    # El más reciente primero: confirma la 11 y contradice la 12.
    r = acotar(
        date(2026, 1, 1),
        [
            TasaDecretada("99999911", Decimal("0.35"), Decimal(0)),
            TasaDecretada("99999912", Decimal("0.50"), Decimal(0)),
        ],
    )
    assert r.partidas == ["99999911"] and r.conflictos == ["99999912"]
    # Uno más viejo encuentra el tramo desconocido y no lo llena.
    viejo = acotar(date(2024, 12, 20), [TasaDecretada("99999911", Decimal("0.10"), Decimal(0))])
    assert viejo.partidas == [] and viejo.sin_tasa_previa == 1

    versiones = pg_session.scalars(
        sa.select(TariffFraction)
        .where(TariffFraction.code == "99999911")
        .order_by(TariffFraction.valid_from)
    ).all()
    assert [(v.valid_from, v.valid_to, v.igi_rate) for v in versiones] == [
        (date(2022, 12, 12), date(2025, 12, 31), None),
        (date(2026, 1, 1), None, Decimal("0.350000")),
    ]
    nicos = pg_session.scalars(
        sa.select(Nico).where(Nico.full_code == "9999991100").order_by(Nico.valid_from)
    ).all()
    assert [n.tariff_fraction_id for n in nicos] == [versiones[0].id, versiones[1].id]
    intacta = pg_session.scalars(
        sa.select(TariffFraction).where(TariffFraction.code == "99999912")
    ).one()
    assert intacta.igi_rate == Decimal("0.200000") and intacta.valid_to is None, (
        "el conflicto no se toca"
    )
