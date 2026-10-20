"""El Anexo 2.4.1 del DOF 25-nov-2022, en HTML (ADR 0003, actualización 20-oct).

Textos del anexo real. Lo que se protege: que cada tabla caiga en su numeral,
que cada NOM se quede con SU acotación, que «Excepto» también acote, que el
anexo termine donde empieza el 2.5.1, y que una NOM listada para sólo algunos
NICO no se convierta en una exigencia de toda la fracción.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from ingestion.se.anexo_2_4_1 import parse_html

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

CABECERA = (
    "<tr><td>Fracción arancelaria / NICO</td><td>Descripción</td><td>NOM / Acotación</td></tr>"
)

HTML = f"""
<html><body><table><tr><td>
<p>ANEXO 2.4.1 Fracciones arancelarias … (Anexo de NOM's)</p>
<p>1.- Se identifican las fracciones arancelarias y nomenclatura de la Tarifa, …:</p>
<table>
{CABECERA}
<tr><td>0402.10.01</td><td>Leche en polvo o en pastillas.</td>
    <td rowspan='2'>NOM-222-SCFI/SAGARPA-<br>2018<br>Únicamente: Leche en polvo o deshidratada descremada.</td></tr>
<tr><td>00</td><td>Leche en polvo o en pastillas.</td></tr>
<tr><td>8528.59.01</td><td>Los demás.</td>
    <td rowspan='2'>NOM-019-SCFI-1998 Únicamente: Los utilizados exclusiva o principalmente con
    máquinas automáticas.<br>NOM-001-SCFI-2018 Únicamente: Los no destinados a utilizarse con
    máquinas automáticas.</td></tr>
<tr><td>00</td><td>Los demás.</td></tr>
<tr><td>8519.81.10</td><td>Reproductores.</td>
    <td rowspan='2'>NOM-032-ENER-2013 Excepto: Cuando requieran una fuente de alimentación
    externa.<br>NOM-001-SCFI-2018</td></tr>
<tr><td>00</td><td>Reproductores.</td></tr>
<tr><td>9503.00.99</td><td>Los demás.</td><td>NOM-015-SCFI-2007</td></tr>
<tr><td>01</td><td>Juguetes.</td><td>NOM-015-SCFI-2007</td></tr>
</table>
<p>3.- Se identifican las fracciones … información comercial y sanitaria:</p>
<table>
{CABECERA}
<tr><td>2202.99.04</td><td>Que contengan leche.</td><td>NOM-051-SCFI/SSA1-2010</td></tr>
</table>
<p>4.- Se identifican las fracciones … cuya exportación …:</p>
<table>
{CABECERA}
<tr><td>0106.20.01</td><td>Reptiles.</td><td>NOM-059-SEMARNAT-2010</td></tr>
</table>
<p>ANEXO 2.5.1 Fracciones arancelarias … cuotas compensatorias.</p>
<table>
<tr><td>0207.13.04</td><td>Pollo</td><td>NOM-999-XXXX-2099</td></tr>
</table>
</td></tr></table></body></html>
"""


def _de(fraccion: str) -> dict[str, str | None]:
    return {f.nom_code: f.scope_note for f in parse_html(HTML) if f.fraction_code == fraccion}


def test_cada_tabla_en_su_numeral_y_el_3_fuera() -> None:
    numerales = {(f.fraction_code, f.numeral) for f in parse_html(HTML)}
    assert ("04021001", 1) in numerales
    assert ("01062001", 4) in numerales
    assert not any(f == "22029904" for f, _ in numerales), "el numeral 3 no es tabular"


def test_el_anexo_termina_donde_empieza_el_2_5_1() -> None:
    assert not any(f.nom_code == "NOM-999-XXXX-2099" for f in parse_html(HTML))


def test_el_codigo_partido_en_dos_lineas_se_une() -> None:
    assert "NOM-222-SCFI/SAGARPA-2018" in _de("04021001")


def test_cada_nom_se_queda_con_su_acotacion() -> None:
    """8528.59.01: la lectura del PDF le pegaba a NOM-001 la acotación de NOM-019."""
    notas = _de("85285901")
    assert notas["NOM-019-SCFI-1998"].startswith("Únicamente: Los utilizados")
    assert notas["NOM-001-SCFI-2018"].startswith("Únicamente: Los no destinados")


def test_excepto_tambien_acota_y_la_otra_nom_queda_libre() -> None:
    notas = _de("85198110")
    assert notas["NOM-032-ENER-2013"].startswith("Excepto: Cuando requieran")
    assert notas["NOM-001-SCFI-2018"] is None


def test_los_nico_que_lleva_cada_nom() -> None:
    (fila,) = [f for f in parse_html(HTML) if f.fraction_code == "95030099"]
    assert fila.nicos_listados == ("01",)


def test_las_filas_antiguas_se_siguen_leyendo_como_unicamente() -> None:
    from apps.api.routers.pedimentos import _acotacion

    assert _acotacion("Leche en polvo descremada.") == "Únicamente: Leche en polvo descremada."
    assert _acotacion("Excepto: Cuando requieran …") == "Excepto: Cuando requieran …"
    assert _acotacion("Sólo los NICO 01 de la fracción.") == "Sólo los NICO 01 de la fracción."


# ── Carga (contra Postgres, en una transacción que se revierte) ──────────────


@pytest.mark.integration
def test_carga_la_version_nueva_cierra_la_anterior_y_acota_por_nico(
    pg_session: Session,  # noqa: F811
) -> None:
    import sqlalchemy as sa
    from database.models import FractionNomRequirement, TariffFraction
    from ingestion.se.load import FUENTE, VIGENCIA_2022_11, cargar_version_2022_11

    if not pg_session.scalar(sa.select(sa.func.count()).select_from(TariffFraction)):
        pytest.skip("sin tarifa cargada no hay contra qué validar las fracciones")
    filas = parse_html(HTML)
    creadas, _, omitidas = cargar_version_2022_11(
        pg_session, filas, content_hash="0" * 64, minio_key="se/prueba.html"
    )
    otra_vez, cerradas_otra_vez, _ = cargar_version_2022_11(
        pg_session, filas, content_hash="0" * 64, minio_key="se/prueba.html"
    )
    assert creadas + len(omitidas) == len(filas)
    assert otra_vez == 0 and cerradas_otra_vez == 0, "idempotente"

    abiertas_viejas = pg_session.scalar(
        sa.select(sa.func.count())
        .select_from(FractionNomRequirement)
        .where(
            FractionNomRequirement.source_url == FUENTE,
            FractionNomRequirement.valid_to.is_(None),
        )
    )
    assert abiertas_viejas == 0, "la versión anterior queda cerrada, no borrada"

    juguete = pg_session.scalars(
        sa.select(FractionNomRequirement).where(
            FractionNomRequirement.fraction_code == "95030099",
            FractionNomRequirement.valid_from == VIGENCIA_2022_11,
        )
    ).first()
    nicos = pg_session.scalar(
        sa.text(
            "SELECT count(*) FROM regulatory.nicos n JOIN regulatory.tariff_fractions f "
            "ON f.id = n.tariff_fraction_id WHERE f.code = '95030099' AND n.valid_to IS NULL"
        )
    )
    if juguete is not None and nicos and nicos > 1:
        assert juguete.scope_note is not None
        assert juguete.scope_note.startswith("Sólo los NICO 01"), "no se exige a toda la fracción"
    leche = pg_session.scalars(
        sa.select(FractionNomRequirement).where(
            FractionNomRequirement.fraction_code == "04021001",
            FractionNomRequirement.valid_from == VIGENCIA_2022_11,
        )
    ).first()
    if leche is not None:
        assert leche.valid_from == date(2022, 12, 12)
        assert leche.published_at == date(2022, 11, 25)
