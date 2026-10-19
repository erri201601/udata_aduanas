"""Tests de `ingestion.dof.sumario` -- fixture offline, construida con la
MISMA estructura verificada a mano contra `https://dof.gob.mx/sumario.xml`
el 13-oct-2026 (no se depende de la red para que el test sea determinista)."""

from __future__ import annotations

import pytest
from ingestion.dof.sumario import (
    clasificar_event_kind,
    es_relevante_comercio_exterior,
    parse_sumario,
)

pytestmark = pytest.mark.unit

_FIXTURE = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<rss version="2.0">
<channel>
<title>DOF - Sumario</title>
<item>
    <title>PODER EJECUTIVO PRESIDENCIA DE LA REPUBLICA</title>
    <link><![CDATA[https://dof.gob.mx/nota_detalle.php?codigo=5800977&fecha=13/10/2026]]></link>
    <description><![CDATA[Decreto por el que se modifica la Tarifa de la Ley de los Impuestos Generales de Importaci&oacute;n y de Exportaci&oacute;n.]]></description>
    <valueDate>13/10/2026</valueDate>
</item>
<item>
    <title>PODER EJECUTIVO SECRETARIA DE SALUD</title>
    <link><![CDATA[https://dof.gob.mx/nota_detalle.php?codigo=5800980&fecha=13/10/2026]]></link>
    <description><![CDATA[Convenio Espec&iacute;fico de Coordinaci&oacute;n en materia de salud p&uacute;blica.]]></description>
    <valueDate>13/10/2026</valueDate>
</item>
<item>
    <title>ORGANISMOS AUTONOMOS BANCO DE MEXICO</title>
    <link><![CDATA[https://dof.gob.mx/nota_detalle.php?codigo=5800993&fecha=13/10/2026]]></link>
    <description><![CDATA[Tipo de cambio para solventar obligaciones denominadas en moneda extranjera.]]></description>
    <valueDate>13/10/2026</valueDate>
</item>
<item>
    <title>PODER EJECUTIVO SECRETARIA DE ECONOMIA</title>
    <link><![CDATA[https://dof.gob.mx/nota_detalle.php?codigo=5800999&fecha=13/10/2026]]></link>
    <description><![CDATA[Acuerdo por el que se abroga el Acuerdo por el que se establecen las reglas de operaci&oacute;n del PROSEC.]]></description>
    <valueDate>13/10/2026</valueDate>
</item>
</channel>
</rss>
""".encode("iso-8859-1")


def test_parsea_las_cuatro_entradas() -> None:
    items = parse_sumario(_FIXTURE)

    assert len(items) == 4
    assert items[0].codigo == "5800977"
    assert items[0].value_date.isoformat() == "2026-10-13"
    assert "Importación" in items[0].description  # el acento ya desescapado
    assert items[0].source_url == (
        "https://dof.gob.mx/nota_detalle.php?codigo=5800977&fecha=13/10/2026"
    )


def test_filtra_solo_comercio_exterior_y_excluye_banxico() -> None:
    items = parse_sumario(_FIXTURE)
    relevantes = [i for i in items if es_relevante_comercio_exterior(i)]

    assert {i.codigo for i in relevantes} == {"5800977", "5800999"}


def test_clasifica_amendment_y_repeal() -> None:
    items = parse_sumario(_FIXTURE)
    por_codigo = {i.codigo: i for i in items}

    assert clasificar_event_kind(por_codigo["5800977"]) == "AMENDMENT"
    assert clasificar_event_kind(por_codigo["5800999"]) == "REPEAL"


def test_clasifica_publication_por_defecto() -> None:
    items = parse_sumario(_FIXTURE)
    salud = next(i for i in items if i.codigo == "5800980")

    assert clasificar_event_kind(salud) == "PUBLICATION"
