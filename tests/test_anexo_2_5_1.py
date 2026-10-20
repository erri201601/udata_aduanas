"""El Anexo 2.5.1 (ADR 0017): de las tablas del DOF a un índice de cuotas.

El fixture reproduce, con textos del anexo real (DOF 25-nov-2022), cada forma
que tiene la tabla y que el parser tiene que resolver: celdas combinadas, una
tabla de continuación tras un salto de página, la nota de alcance sin empresa,
dos países en una celda, «Y TODAS LAS DEMÁS» al final de un nombre y dos cuotas
distintas sobre la misma fracción y origen.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from ingestion.se.anexo_2_5_1 import (
    AnexoIlegibleError,
    filas_del_anexo,
    paises_de,
    parse,
)

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

ENCABEZADO = (
    "<tr><td>PRODUCTO</td><td>FRACCION ARANCELARI A TIGIE 2022</td><td>PAÍS</td>"
    "<td>FECHA DE PUBLICACIÓN EN DOF</td><td>EMPRESAS</td><td>CUOTA COMPENSATORIA</td></tr>"
)

HTML = f"""
<html><body>
<table><tr><td>Otra tabla del acuerdo</td></tr></table>
<table>
{ENCABEZADO}
<tr>
  <td rowspan='3'>PIERNA Y MUSLO<br>DE POLLO</td>
  <td rowspan='3'><div>0207.13.04</div><div>0207.14.99</div></td>
  <td rowspan='3'>EUA</td>
  <td>ANTIDUMPING<br>FINAL<br>06/08/2012</td>
  <td>SIMMONS PREPARED FOODS, INC.</td>
  <td>25.7% .</td>
</tr>
<tr>
  <td>EXAMEN<br>27/08/2018</td>
  <td rowspan='2'>TODAS LAS<br>DEMÁS<br>EXPORTADORAS</td>
  <td>25.7% .</td>
</tr>
<tr>
  <td>EXAMEN<br>27/08/2018</td>
  <td>LA SECRETARÍA DETERMINA NO APLICAR LA CUOTA COMPENSATORIA DEFINITIVA.</td>
</tr>
<tr>
  <td rowspan='2'>FTALATO DE DIOCTILO</td>
  <td rowspan='2'>2917.32.01</td>
  <td rowspan='2'>COREA<br>EUA</td>
  <td rowspan='2'>ANTIDUMPING FINAL 01/09/2021</td>
  <td rowspan='2'>TODAS LAS EXPORTADORAS</td>
  <td rowspan='2'>$0.27 DÓLARES POR KILOGRAMO.</td>
</tr>
<tr></tr>
</table>
<table>
<tr>
  <td>TUBERÍA DE ACERO AL CARBONO</td>
  <td>7305.11.02</td>
  <td>EUA</td>
  <td>ANTIDUMPING FINAL 20/04/2016</td>
  <td></td>
  <td>LAS IMPORTACIONES DE TUBERÍA CON COSTURA LONGITUDINAL RECTA Y HELICOIDAL.</td>
</tr>
<tr>
  <td></td><td></td><td></td>
  <td>EXAMEN 12/08/2021</td>
  <td>STUPP BROS., INC Y TODAS LAS DEMÁS EXPORTADORAS</td>
  <td>$575.01 DÓLARES POR TONELADA MÉTRICA.</td>
</tr>
<tr>
  <td>TUBERÍA DE ACERO SIN COSTURA</td>
  <td>7304.19.99</td>
  <td>CHINA</td>
  <td>ANTIDUMPING FINAL 24/02/2011</td>
  <td>TODAS LAS EXPORTADORAS</td>
  <td>$1,252 DÓLARES POR TONELADA MÉTRICA.</td>
</tr>
<tr>
  <td>TUBERÍA DE ACERO SIN COSTURA</td>
  <td><div>7304.19.01</div><div>7304.19.99</div></td>
  <td>CHINA</td>
  <td>ANTIDUMPING FINAL 07/01/2014</td>
  <td>TODAS LAS EXPORTADORAS</td>
  <td>$1,568.92 DÓLARES POR TONELADA MÉTRICA.</td>
</tr>
</table>
<table><tr><td>En el documento que usted está visualizando</td></tr></table>
</body></html>
"""


def _de(filas: list, fraccion: str, pais: str) -> list:
    return [f for f in filas if f.fraction_code == fraccion and f.origin_country == pais]


def test_lee_todas_las_tablas_del_anexo_y_para_en_la_siguiente() -> None:
    filas = filas_del_anexo(HTML)
    assert len(filas) == 9, "las dos tablas del anexo, sin encabezado ni la tabla del pie"
    assert all(len(f) == 6 for f in filas)


def test_las_celdas_combinadas_alcanzan_a_cada_fila() -> None:
    pollo = _de(parse(HTML), "02071304", "US")
    assert {f.exporter_text for f in pollo} == {
        "SIMMONS PREPARED FOODS, INC.",
        "TODAS LAS DEMÁS EXPORTADORAS",
    }
    assert all(f.product_description == "PIERNA Y MUSLO DE POLLO" for f in pollo)


def test_una_fraccion_por_fila() -> None:
    fracciones = {
        f.fraction_code for f in parse(HTML) if f.product_description.startswith("PIERNA")
    }
    assert fracciones == {"02071304", "02071499"}


def test_la_nota_de_la_misma_empresa_se_suma_a_su_cuota() -> None:
    (residual,) = [f for f in _de(parse(HTML), "02071304", "US") if f.applies_to_all_others]
    assert residual.duty_text.startswith("25.7%")
    assert "NO APLICAR" in residual.duty_text


def test_el_historial_y_sus_fechas() -> None:
    (simmons,) = [
        f for f in _de(parse(HTML), "02071304", "US") if f.exporter_text.startswith("SIMMONS")
    ]
    assert [r.fecha for r in simmons.resolution_history] == [date(2012, 8, 6), date(2018, 8, 27)]
    assert simmons.resolution_history[0].tipo == "ANTIDUMPING FINAL"
    assert simmons.latest_resolution_date == date(2018, 8, 27)


def test_dos_paises_en_una_celda_son_dos_filas() -> None:
    assert {f.origin_country for f in parse(HTML) if f.fraction_code == "29173201"} == {"KR", "US"}


def test_una_pagina_nueva_continua_el_registro_y_el_alcance_va_aparte() -> None:
    (stupp,) = _de(parse(HTML), "73051102", "US")
    assert stupp.exporter_text == "STUPP BROS., INC Y TODAS LAS DEMÁS EXPORTADORAS"
    assert stupp.applies_to_all_others, "«Y TODAS LAS DEMÁS» al final también cuenta"
    assert stupp.duty_text == "$575.01 DÓLARES POR TONELADA MÉTRICA."
    assert stupp.scope_note is not None and "HELICOIDAL" in stupp.scope_note
    assert [r.fecha.year for r in stupp.resolution_history] == [2016, 2021]


def test_dos_cuotas_sobre_la_misma_fraccion_no_se_mezclan() -> None:
    sin_costura = _de(parse(HTML), "73041999", "CN")
    assert sorted(f.first_resolution_date for f in sin_costura) == [
        date(2011, 2, 24),
        date(2014, 1, 7),
    ]
    assert len({f.duty_text for f in sin_costura}) == 2


def test_la_cuota_se_guarda_como_texto() -> None:
    """Regla 2.5.3: manda la resolución. El anexo no da números."""
    assert all(isinstance(f.duty_text, str) for f in parse(HTML))


def test_un_pais_desconocido_detiene_la_carga() -> None:
    with pytest.raises(AnexoIlegibleError, match="ATLANTIDA"):
        paises_de("CHINA ATLANTIDA")


def test_sin_la_tabla_del_anexo_no_se_inventa_nada() -> None:
    with pytest.raises(AnexoIlegibleError):
        filas_del_anexo("<table><tr><td>nada</td></tr></table>")


# ── Carga (contra Postgres, en una transacción que se revierte) ──────────────


@pytest.mark.integration
def test_la_carga_es_idempotente_y_omite_lo_que_no_esta_en_la_tarifa(
    pg_session: Session,  # noqa: F811
) -> None:
    import sqlalchemy as sa
    from database.models import CompensatoryDutyListing, TariffFraction
    from ingestion.se.load import cargar_anexo_2_5_1

    if not pg_session.scalar(sa.select(sa.func.count()).select_from(TariffFraction)):
        pytest.skip("sin tarifa cargada no hay contra qué validar las fracciones")
    pg_session.execute(sa.delete(CompensatoryDutyListing))
    filas = parse(HTML)
    primera, omitidas = cargar_anexo_2_5_1(
        pg_session, filas, content_hash="0" * 64, minio_key="se/prueba.html"
    )
    segunda, _ = cargar_anexo_2_5_1(
        pg_session, filas, content_hash="0" * 64, minio_key="se/prueba.html"
    )
    assert primera + len(omitidas) == len(filas)
    assert segunda == 0
    fila = pg_session.scalars(
        sa.select(CompensatoryDutyListing).where(
            CompensatoryDutyListing.fraction_code == "73051102"
        )
    ).first()
    if fila is not None:
        assert fila.data_origin == "OFFICIAL"
        assert fila.valid_from == date(2022, 12, 12)
        assert fila.resolution_history[0] == {"tipo": "ANTIDUMPING FINAL", "fecha": "2016-04-20"}
