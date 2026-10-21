"""Qué toca una publicación del DOF (ADR 0022). Textos de notas reales."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from ingestion.dof.afectacion import fracciones_de, leer, noms_del_titulo, vigencia_de

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

DECRETO_9803 = """<html><body><table><tr><td>
<p>DECRETO por el que se modifica la Tarifa de la Ley de los Impuestos Generales…</p>
<table><tr><td>9803.00.01</td><td>Partes y componentes para el ensamble de automóviles…</td>
<td>Kg</td><td>Ex.</td><td>Ex.</td></tr></table>
<p>TRANSITORIO</p><p>ÚNICO. El presente decreto entra en vigor al día siguiente de su
publicación en el Diario Oficial de la Federación y tendrá una vigencia de cinco años
contados a partir de su entrada en vigor.</p>
</td></tr></table>
<p>En el documento que usted está visualizando puede haber texto…</p>
<div>DOLAR 18.4253 · 0102.21.01</div>
</body></html>"""

DECRETO_DIC_2025 = (
    "<p>9619.00.99 Las demás. Pza 35 Ex.</p><p>Transitorios</p><p>Primero. El presente "
    "Decreto entrará en vigor el primero de enero de 2026.</p>"
)

CODIGO_DE_CONDUCTA = (
    "<p>… conforme a la NOM-046-SSA2-2005 …</p><p>TRANSITORIOS</p><p>PRIMERO.- El presente "
    "Acuerdo entrará en vigor al día siguiente de su publicación en el Diario Oficial.</p>"
)


def test_la_fraccion_de_la_tabla_y_la_entrada_en_vigor_con_su_fin() -> None:
    a = leer(
        DECRETO_9803,
        titulo="Decreto por el que se modifica la Tarifa",
        publicada=date(2026, 10, 13),
    )
    assert a.fracciones == ("98030001",)
    assert a.entra_en_vigor == date(2026, 10, 14)
    assert a.vigencia_hasta == date(2031, 10, 13), "cinco años, el día antes del aniversario"


def test_lo_de_la_columna_lateral_del_dof_no_cuenta() -> None:
    assert "01022101" not in fracciones_de(DECRETO_9803)


def test_el_primero_de_enero_en_minusculas() -> None:
    assert vigencia_de(DECRETO_DIC_2025, date(2025, 12, 29)) == (date(2026, 1, 1), None)


def test_las_nom_salen_del_titulo_no_del_cuerpo() -> None:
    a = leer(
        CODIGO_DE_CONDUCTA,
        titulo="Acuerdo por el que se expide el Código de Conducta",
        publicada=date(2026, 10, 19),
    )
    assert a.noms == ()
    assert noms_del_titulo(
        "Aviso de consulta pública del proyecto de cancelación de la Norma Oficial Mexicana NOM-077-SSA1-1994"
    ) == ("NOM-077-SSA1-1994",)


def test_un_aviso_de_consulta_no_entra_en_vigor() -> None:
    assert vigencia_de("<p>Aviso de consulta pública…</p>", date(2026, 10, 21)) == (None, None)


# ── Contra Postgres, en una transacción que se revierte ──────────────────────


@pytest.mark.integration
def test_leer_notas_llena_el_evento_y_sentinel_lo_cruza_con_los_clientes(
    pg_session: Session,  # noqa: F811
) -> None:
    from datetime import UTC, datetime

    import sqlalchemy as sa
    from apps.api.routers.sentinel import _eventos_con_impacto
    from database.models import PedimentoItem, RegulatoryEvent
    from ingestion.dof.load import leer_notas_pendientes

    fraccion_de_cliente = pg_session.scalar(
        sa.select(PedimentoItem.declared_fraction_code)
        .where(PedimentoItem.declared_fraction_code.isnot(None))
        .limit(1)
    )
    if fraccion_de_cliente is None:
        pytest.skip("sin partidas no hay clientes con los que cruzar")
    con_puntos = f"{fraccion_de_cliente[:4]}.{fraccion_de_cliente[4:6]}.{fraccion_de_cliente[6:]}"
    nota = DECRETO_9803.replace("9803.00.01", con_puntos)

    pg_session.execute(sa.update(RegulatoryEvent).values(note_content_hash="ya-leida"))
    evento = RegulatoryEvent(
        title="Decreto por el que se modifica la Tarifa (prueba)",
        event_kind="AMENDMENT",
        data_origin="SYNTHETIC",
        valid_from=date(2099, 1, 1),
        published_at=date(2099, 1, 1),
        source_url="https://www.dof.gob.mx/nota_detalle.php?codigo=99999999&fecha=01/01/2099",
        content_hash="0" * 64,
        retrieved_at=datetime.now(UTC),
    )
    pg_session.add(evento)
    pg_session.flush()

    pedidas: list[str] = []

    def descargar(url: str) -> bytes:
        pedidas.append(url)
        return nota.encode()

    leidas, con_fracciones = leer_notas_pendientes(
        pg_session, descargar=descargar, guardar_raw=lambda datos, codigo: "f" * 64
    )
    assert (leidas, con_fracciones) == (1, 1)
    assert pedidas == ["https://dof.gob.mx/nota_detalle.php?codigo=99999999&fecha=01/01/2099"], (
        "sin www: el certificado de www.dof.gob.mx no coincide"
    )
    assert evento.affected_fraction_codes == [fraccion_de_cliente]
    assert evento.effective_date == date(2099, 1, 2)
    assert evento.valid_to == date(2104, 1, 1)
    assert evento.note_content_hash == "f" * 64

    otra_vez, _ = leer_notas_pendientes(
        pg_session, descargar=descargar, guardar_raw=lambda datos, codigo: "f" * 64
    )
    assert otra_vez == 0, "una nota leída no se vuelve a leer"

    impacto = next(
        e for e in _eventos_con_impacto(pg_session, date(2099, 1, 2)) if "99999999" in e.url
    )
    assert impacto.nota_leida
    assert fraccion_de_cliente in impacto.fracciones_de_clientes
    assert impacto.partidas_afectadas >= 1
