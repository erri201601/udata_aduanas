"""EBTI como casos comparables (ADR 0020).

El CSV de prueba copia la forma del publicado por la Comisión (BOM, comillas,
saltos de línea dentro de los campos, la errata «DATE_OF _ISSUE», códigos con
asteriscos de relleno).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from database.repositories.comparables import criterio_de
from ingestion.ebti.ebti import CsvIlegibleError, codigo_de, parse_csv, publicaciones

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

CABECERA = (
    '﻿"BTI_REFERENCE","ISSUING_COUNTRY","START_DATE_OF_VALIDITY","END_DATE_OF_VALIDITY",'
    '"NOMENCLATURE_CODE","CLASSIFICATION_JUSTIFICATION","STATUS","INVALIDATION_REASON",'
    '"INVALIDATION_JUSTIFICATION","LANGUAGE","PLACE_OF_ISSUE","DATE_OF _ISSUE",'
    '"NAME_AND_ADDRESS","DESCRIPTION_OF_GOODS","KEYWORDS"\n'
)
CSV = CABECERA + (
    '"FRBTIFR-2026-1","FR","2026-10-19 00:00:00","2029-10-18 00:00:00","76151080**************",'
    '"Classement déterminé par les règles générales 1 et 6.\nNote 1 du chapitre 76.","VALID","","",'
    '"fr","","2026-10-19 00:00:00","Douane\nParis","Autocuiseur en aluminium de 6 litres, avec soupape.",'
    '"AUTOCUISEURS,EN ALUMINIUM"\n'
    '"DEBTI20367/25-1","DE","2025-08-01 00:00:00","2026-07-19 00:00:00","70197100**************",'
    '"Einreihung nach AV 1 und 6.","INVALID","64","","de","","2025-07-22 00:00:00","Zoll","Glasvlies.",""\n'
)


def test_lee_el_csv_de_la_comision() -> None:
    validas = parse_csv(CSV)
    assert [b.referencia for b in validas] == ["FRBTIFR-2026-1", "DEBTI20367/25-1"]
    olla = validas[0]
    assert olla.codigo_nc == "76151080" and olla.hs6 == "761510"
    assert olla.desde == date(2026, 10, 19) and olla.hasta == date(2029, 10, 18)
    assert olla.valida and olla.idioma == "fr"
    assert "Note 1 du chapitre 76" in olla.justificacion


def test_una_invalidada_lo_dice_y_su_motivo_no_se_interpreta() -> None:
    vidrio = parse_csv(CSV)[1]
    assert not vidrio.valida
    assert vidrio.motivo_invalidacion == "64"
    assert "motivo_invalidacion=64" in vidrio.categorias


def test_los_asteriscos_son_relleno() -> None:
    assert codigo_de("6914900090************") == "6914900090"


def test_columnas_distintas_paran_la_carga() -> None:
    with pytest.raises(CsvIlegibleError):
        parse_csv('"A","B"\n"1","2"\n')


def test_el_extracto_es_la_justificacion_literal() -> None:
    extracto, origen = criterio_de(parse_csv(CSV)[0].texto)
    assert origen == "justificacion"
    assert extracto.startswith("Classement déterminé par les règles générales 1 et 6.")


def test_la_lista_de_diarias_va_de_la_mas_antigua_a_la_mas_reciente() -> None:
    html = (
        "<td>2026-10-20 04:41:13</td><td class='x'>EBTI_20261020_044113.zip</td>"
        "<td>2026-10-17 04:40:11</td>\n<td>\nEBTI_20261017_044011.zip\n</td>"
    )
    assert publicaciones(html) == [
        ("2026-10-17 04:40:11", "EBTI_20261017_044011.zip"),
        ("2026-10-20 04:41:13", "EBTI_20261020_044113.zip"),
    ]


@pytest.mark.integration
def test_la_carga_inserta_y_una_invalidacion_posterior_la_marca(
    pg_session: Session,  # noqa: F811
) -> None:
    import dataclasses

    import sqlalchemy as sa
    from database.models import ComparableRuling
    from ingestion.ebti.load import cargar

    pg_session.execute(
        sa.delete(ComparableRuling).where(ComparableRuling.ruling_number == "FRBTIFR-2026-1")
    )
    olla = parse_csv(CSV)[0]
    assert cargar(pg_session, olla, content_hash="0" * 64, minio_key="ebti/x.zip")
    pg_session.flush()
    invalidada = dataclasses.replace(olla, valida=False, hasta=date(2027, 1, 1))
    assert not cargar(pg_session, invalidada, content_hash="1" * 64, minio_key="ebti/y.zip")
    pg_session.flush()
    fila = pg_session.scalars(
        sa.select(ComparableRuling).where(ComparableRuling.ruling_number == "FRBTIFR-2026-1")
    ).one()
    assert fila.authority == "EBTI" and fila.collection == "FR"
    assert fila.hs6_codes == ["761510"] and fila.tariff_codes == ["76151080"]
    assert fila.is_revoked and fila.valid_to == date(2027, 1, 1)
    assert fila.data_origin == "PUBLIC"
    assert "showHeader=false" in fila.source_url
