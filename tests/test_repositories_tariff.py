"""Tests del prefiltro de candidatas del catálogo arancelario.

`unit` — que la normalización de acentos ocurra en el SQL y no después en
Python: si se hiciera al traer las filas, el `WHERE` seguiría descartando la
partida correcta antes de que nadie pudiera normalizar nada.
`integration` — contra PostgreSQL real, porque `unaccent` es una extensión de
la base y un doble no probaría que está instalada ni que se aplica.

Los términos son inventados a propósito («zzqxon», «wwvkun»). Con 8 136
fracciones reales cargadas, una palabra del idioma haría que el test pasara o
fallara según qué haya en la tarifa ese día.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from database.models import TariffFraction
from database.repositories.tariff import TariffCatalogRepository

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

pytestmark = pytest.mark.unit

FECHA = date(2026, 1, 23)


def _sql(sentencia: object) -> str:
    return " ".join(
        str(sentencia.compile(compile_kwargs={"literal_binds": True})).split()  # type: ignore[attr-defined]
    )


def _fraccion(sesion: sa.orm.Session, code: str, description: str, specificity: int) -> None:
    sesion.add(
        TariffFraction(
            code=code,
            chapter=code[:2],
            heading=code[:4],
            subheading=code[:6],
            description=description,
            specificity=specificity,
            data_origin="OFFICIAL",
            valid_from=date(2022, 6, 7),
            source_url="https://x",
            content_hash="h",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    sesion.flush()


def test_los_acentos_se_normalizan_en_la_base_no_en_python() -> None:
    """`unaccent` a los dos lados, dentro del SQL.

    Un pedimento se escribe en mayúsculas y sin acentos; la tarifa lleva
    acentos. Si la comparación no los normaliza, «portatiles» no encuentra
    «portátiles» y el motor se queda sin la partida correcta.
    """
    sesion = MagicMock()
    TariffCatalogRepository(sesion).headings(on_date=FECHA, terms=["portatiles"])
    sql = _sql(sesion.execute.call_args.args[0]).lower()

    assert sql.count("unaccent") >= 2, f"falta normalizar los dos lados: {sql}"
    assert "where" in sql and "unaccent" in sql.split("where", 1)[1]


@pytest.mark.integration
def test_encuentra_la_partida_aunque_el_termino_venga_sin_acentos(
    pg_session: sa.orm.Session,  # noqa: F811
) -> None:
    _fraccion(pg_session, "99911001", "Artículo de prueba zzqxón.", 1)

    candidatas = TariffCatalogRepository(pg_session).headings(on_date=FECHA, terms=["zzqxon"])

    assert "9991" in {c.code for c in candidatas}


@pytest.mark.integration
def test_primero_la_partida_que_casa_mas_terminos(pg_session: sa.orm.Session) -> None:  # noqa: F811
    """Cubrir más de la consulta pesa más que ser específico.

    Antes se ordenaba sólo por `specificity`, y una partida que casaba una
    palabra genérica adelantaba a la que casaba todas. Con la tarifa completa
    eso mandaba cables eléctricos al capítulo 98.
    """
    _fraccion(pg_session, "99921001", "Prueba zzqxón wwvkún.", 1)
    _fraccion(pg_session, "99931001", "Prueba wwvkún solamente.", 9)

    candidatas = TariffCatalogRepository(pg_session).headings(
        on_date=FECHA, terms=["zzqxon", "wwvkun"]
    )
    codigos = [c.code for c in candidatas if c.code in {"9992", "9993"}]

    assert codigos[0] == "9992", f"la que casa dos términos va primero: {codigos}"


# ── La jerarquía completa y el mejor nivel (Persona 1, 23-sep) ──────────────


def _partida_texto(sesion: sa.orm.Session, code: str, description: str) -> None:
    """Un nodo de `tariff_headings`: partida (4) o subpartida (6)."""
    from database.models import TariffHeading

    sesion.add(
        TariffHeading(
            code=code,
            level=len(code),
            chapter=code[:2],
            description=description,
            data_origin="OFFICIAL",
            valid_from=date(2022, 6, 7),
            source_url="https://x",
            content_hash="h",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    sesion.flush()


@pytest.mark.integration
def test_una_fraccion_se_encuentra_por_el_texto_de_su_partida(
    pg_session: sa.orm.Session,  # noqa: F811
) -> None:
    """«De acero inoxidable.» no dice de qué. El sujeto está en la partida.

    45 % de las descripciones de fracción tienen menos de 25 caracteres. Sin
    la jerarquía, buscar en ellas es buscar en fragmentos sin sujeto.
    """
    _fraccion(pg_session, "99929301", "De acero zzqxón.", 1)
    _partida_texto(pg_session, "9992", "Artículos de uso wwvkún, de fundición o acero.")

    candidatas = TariffCatalogRepository(pg_session).headings(on_date=FECHA, terms=["wwvkun"])

    assert [c.code for c in candidatas] == ["9992"], "no se buscó en el texto de la partida"


@pytest.mark.integration
def test_solo_entran_las_partidas_que_mas_terminos_cubren(
    pg_session: sa.orm.Session,  # noqa: F811
) -> None:
    """La RGI 3 c) elige la última en orden numérico y no mira el orden de
    pertinencia. Una partida que roza un término de dos no puede competir con
    la que cubre los dos, o el ruido acaba ganando por numeración."""
    _fraccion(pg_session, "99931001", "Objeto zzqxón wwvkún.", 1)
    _fraccion(pg_session, "99941001", "Objeto zzqxón solamente.", 1)

    candidatas = TariffCatalogRepository(pg_session).headings(
        on_date=FECHA, terms=["zzqxon", "wwvkun"]
    )

    assert [c.code for c in candidatas] == ["9993"], "la que cubre menos no debe entrar"


@pytest.mark.integration
def test_si_nada_cubre_dos_terminos_se_devuelve_lo_que_cubre_uno(
    pg_session: sa.orm.Session,  # noqa: F811
) -> None:
    """El mejor nivel es el que EXISTA, no un umbral escrito a mano.

    Probé ≥2 y ≥3 fijos: dejaban una vajilla de porcelana en cero candidatas.
    """
    _fraccion(pg_session, "99951001", "Objeto zzqxón solamente.", 1)

    candidatas = TariffCatalogRepository(pg_session).headings(
        on_date=FECHA, terms=["zzqxon", "wwvkun"]
    )

    assert [c.code for c in candidatas] == ["9995"], "nunca debe quedar vacío si algo casó"
