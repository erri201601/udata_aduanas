"""Decreto PROSEC (artículo 5) y Regla 8ª: la lectura y la carga (ADR 0011).

Lo que se protege, con eventos que imitan las tablas del PDF:
- «Ex.» es exento (0), no «Ex.» de acotación;
- la columna sale de la posición en el encabezado, no del índice (sector XIX);
- una fila partida entre páginas se une a la anterior sin repetir su cola;
- la Regla 8ª elige el sector más específico («Transporte, excepto Automotriz»).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from database.models import ProsecRate, Regla8aFraction, TariffFraction
from ingestion.se import prosec
from ingestion.se.prosec import filas_de_celdas, nombre_de_sector, tasa
from ingestion.se.regla_8a import fracciones_regla_8a, sector_de

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

ENCABEZADO = [
    (85, 150, "CÓDIGO"),
    (150, 345, "DESCRIPCIÓN"),
    (345, 420, "ARANCEL (%)"),
    (420, 527, "ACOTACIÓN"),
]


def _eventos(*filas: list[tuple[float, float, str]], sector: str = "II") -> list[tuple[str, Any]]:
    return [
        ("ini", None),
        ("sector", (sector, "De la Industria Electrónica")),
        ("fila", ENCABEZADO),
        *[("fila", f) for f in filas],
        ("fin", None),
    ]


@pytest.mark.unit
def test_ex_es_exento_y_el_numero_es_porcentaje() -> None:
    assert tasa("Ex.") == Decimal("0")
    assert tasa("Ex") == Decimal("0")
    assert tasa("5") == Decimal("0.050000")
    assert tasa("2.5") == Decimal("0.025000")
    with pytest.raises(ValueError):
        tasa("Los demás.")


@pytest.mark.unit
def test_el_nombre_del_sector_sin_de_la() -> None:
    assert nombre_de_sector("De la Industria Eléctrica:") == "Industria Eléctrica"
    assert nombre_de_sector("De las Industrias Diversas") == "Industrias Diversas"


@pytest.mark.unit
def test_una_fila_completa_con_acotacion() -> None:
    [f] = filas_de_celdas(
        _eventos(
            [
                (85, 150, "7323.93.05"),
                (150, 345, "De acero inoxidable."),
                (345, 420, "Ex."),
                (420, 527, "Excepto: Moldes,\ndistribuidores de toallas."),
            ]
        )
    )
    assert (f.sector_code, f.sector_name) == ("II", "Industria Electrónica")
    assert f.fraction_code == "73239305"
    assert f.igi_rate == 0
    assert f.is_partial
    assert f.acotacion == "Excepto: Moldes, distribuidores de toallas."


@pytest.mark.unit
def test_la_columna_sale_de_la_posicion_y_no_del_indice() -> None:
    """Sector XIX: el código cae en otra columna espaciadora, más a la derecha."""
    [f] = filas_de_celdas(
        _eventos([(95, 140, "2803.00.02"), (160, 340, "Negro de humo."), (360, 410, "3")])
    )
    assert f.fraction_code == "28030002"
    assert f.igi_rate == Decimal("0.030000")
    assert not f.is_partial


@pytest.mark.unit
def test_la_continuacion_se_une_sin_repetir_la_cola() -> None:
    [f] = filas_de_celdas(
        _eventos(
            [
                (85, 150, "3907.50.99"),
                (150, 345, "Los demás."),
                (345, 420, "3"),
                (420, 527, "Únicamente: Resinas, incluidas las emulsiones,"),
            ],
            [(420, 527, "dispersiones y soluciones.")],
            [(420, 527, "dispersiones y soluciones.")],
        )
    )
    assert f.acotacion == (
        "Únicamente: Resinas, incluidas las emulsiones, dispersiones y soluciones."
    )


@pytest.mark.unit
def test_fuera_del_articulo_5_no_se_lee_nada() -> None:
    fuera = [
        ("sector", ("I", "De la Industria Eléctrica")),
        ("fila", ENCABEZADO),
        ("fila", [(85, 150, "2716.00.01"), (345, 420, "Ex.")]),
    ]
    assert filas_de_celdas(fuera) == []


SECTORES = {
    "XV": "Industria del Transporte, excepto el Sector de la Industria Automotriz y de Autopartes",
    "XIX": "Industrias Automotriz y de Autopartes",
    "XIII": "Industria Siderúrgica",
    "I": "Industria Eléctrica",
}


@pytest.mark.unit
def test_regla_8a_gana_el_sector_mas_especifico() -> None:
    transporte = (
        "Mercancías para el Programa de Promoción Sectorial de la Industria del Transporte, "
        "excepto el Sector de la Industria Automotriz y de Autopartes, cuando las empresas "
        "cuenten con la autorización a que se refiere la Regla 8a."
    )
    automotriz = (
        "Mercancías para el Programa de Promoción Sectorial de la Industria Automotriz y de "
        "Autopartes, cuando las empresas cuenten con la autorización a que se refiere la Regla 8a."
    )
    assert sector_de(transporte, SECTORES)[0] == "XV"
    assert sector_de(automotriz, SECTORES)[0] == "XIX"


@pytest.mark.unit
def test_regla_8a_lleva_la_condicion_y_deja_fuera_lo_que_no_nombra_sector() -> None:
    ok, mal = fracciones_regla_8a(
        [
            (
                "98020013",
                "Mercancías para el Programa de Promoción Sectorial de la Industria "
                "Siderúrgica cuando se trate de productores directos y las empresas cuenten con "
                "la autorización a que se refiere la Regla 8ª.",
            ),
            ("98020026", "Mercancías al amparo de la autorización a que se refiere la Regla 8ª."),
            ("73121005", "No es una 9802."),
        ],
        SECTORES,
    )
    [r] = ok
    assert (r.sector_code, r.scope_note) == ("XIII", "cuando se trate de productores directos")
    assert len(mal) == 1 and mal[0].startswith("98020026")


PROCEDENCIA: dict[str, Any] = {
    "data_origin": "OFFICIAL",
    "source_url": "https://ejemplo.invalido/ligie",
    "content_hash": "0" * 64,
    "retrieved_at": datetime.now(UTC),
}


def _fraccion(session: Session, code: str, descripcion: str = "prueba") -> None:
    session.add(
        TariffFraction(
            code=code,
            chapter=code[:2],
            heading=code[:4],
            subheading=code[:6],
            description=descripcion,
            igi_rate=Decimal("0"),
            valid_from=date(2000, 1, 1),
            **PROCEDENCIA,
        )
    )
    session.flush()


@pytest.mark.integration
def test_carga_prosec_con_dos_acotaciones_de_la_misma_fraccion(pg_session: Session) -> None:  # noqa: F811
    from ingestion.se.load import cargar_prosec
    from ingestion.se.prosec import FilaProsec

    _fraccion(pg_session, "99990001")
    filas = [
        FilaProsec(
            "III", "Industria del Mueble", "99990001", Decimal("0.05"), "Únicamente: A.", "x"
        ),
        FilaProsec("III", "Industria del Mueble", "99990001", Decimal("0.10"), "Excepto: A.", "x"),
        FilaProsec("III", "Industria del Mueble", "99990002", Decimal("0"), None, "x"),
    ]
    creadas, omitidas = cargar_prosec(pg_session, filas, content_hash="a" * 64, minio_key="k")
    otra_vez, _ = cargar_prosec(pg_session, filas, content_hash="a" * 64, minio_key="k")

    assert (creadas, otra_vez) == (2, 0)
    assert len(omitidas) == 1 and "99990002" in omitidas[0], "fracción no vigente: no se carga"
    tasas = sorted(
        r.igi_rate for r in pg_session.query(ProsecRate).filter_by(fraction_code="99990001")
    )
    assert tasas == [Decimal("0.05"), Decimal("0.10")]
    assert all(
        r.valid_from == prosec.VALID_FROM
        for r in pg_session.query(ProsecRate).filter_by(fraction_code="99990001")
    )


@pytest.mark.integration
def test_carga_regla_8a_con_la_procedencia_de_la_ligie(pg_session: Session) -> None:  # noqa: F811
    from ingestion.se.load import cargar_regla_8a
    from ingestion.se.regla_8a import FraccionRegla8a

    _fraccion(pg_session, "98029999")
    n = cargar_regla_8a(
        pg_session,
        [FraccionRegla8a("XIX", "Industrias Automotriz y de Autopartes", "98029999", None)],
    )
    assert n == 1
    fila = pg_session.query(Regla8aFraction).filter_by(fraction_code="98029999").one()
    assert fila.source_url == PROCEDENCIA["source_url"]
    assert fila.valid_from == date(2000, 1, 1)


@pytest.mark.integration
def test_una_contradiccion_del_decreto_no_se_carga_y_se_retira(pg_session: Session) -> None:  # noqa: F811
    """El sector XV lista la 7419.80.02 al 5 % y exenta, sin acotación."""
    from ingestion.se.load import cargar_prosec
    from ingestion.se.prosec import FilaProsec

    _fraccion(pg_session, "99990003")
    una = FilaProsec("XV", "Industria del Transporte", "99990003", Decimal("0.05"), None, "x")
    otra = FilaProsec("XV", "Industria del Transporte", "99990003", Decimal("0"), None, "x")
    # Como pasó el 20-oct: primero entró una sola versión…
    cargar_prosec(pg_session, [una], content_hash="a" * 64, minio_key="k")
    # …y al cargar el decreto completo se ve la contradicción.
    creadas, omitidas = cargar_prosec(pg_session, [una, otra], content_hash="a" * 64, minio_key="k")

    assert creadas == 0
    assert any("NEEDS_VALIDATION" in o and "99990003" in o for o in omitidas)
    assert pg_session.query(ProsecRate).filter_by(fraction_code="99990003").count() == 0
