"""CBP CROSS como casos comparables (ADR 0019).

El fixture es la resolución real HQ 954053 (cable de acero, 1993), recortada.
Lo que se protege: HS6 sin convertir a TIGIE, los capítulos 98/99 fuera, la URL
pública y no la firmada, las revocaciones a la vista, y que una resolución sin
lo mínimo no se carga.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from ingestion.cbp_cross.cross import (
    ResolucionIlegibleError,
    combinar,
    de_la_partida,
    hs6_de,
    parse,
)

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit


def _detalle(**cambios: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "text": "\r\r                            HQ 954053\r\r                            JUNE 30 1993\r\r"
        "CATEGORY:    Classification\r\rTARIFF NO.:  7312.10.10, 7312.10.30\r\r"
        "RE:  Stainless Steel and Galvanized Wire and Wire Rope Assembled\r"
        "     in Mexico From Wires of U.S. Origin; Heading 7312\r",
        "url": "https://sjn0y7-bemsd-cross-prod.s3.us-east-1.amazonaws.com/hq/1993/954053.doc?X-Amz-Expires=900",
        "rulingNumber": "954053",
        "subject": "Stainless Steel and Galvanized Wire and Wire Rope Assembled     in Mexico",
        "categories": None,
        "rulingDate": "1993-06-30T00:00:00",
        "collection": "hq",
        "relatedRulings": None,
        "modifiedBy": None,
        "revokedBy": None,
        "tariffs": "7312.10.10, 7312.10.30, 7312.10.60, 7312.10.90",
        "operationallyRevoked": False,
    }
    return base | cambios


def test_lee_la_resolucion_real() -> None:
    r = parse(_detalle())
    assert r.ruling_number == "954053"
    assert r.ruling_date == date(1993, 6, 30)
    assert r.collection == "hq"
    assert r.tariff_codes == ("7312.10.10", "7312.10.30", "7312.10.60", "7312.10.90")
    assert r.subject.startswith("Stainless Steel and Galvanized Wire and Wire Rope Assembled in")


def test_el_hs6_es_lo_unico_comparable_y_no_se_convierte_a_tigie() -> None:
    assert parse(_detalle()).hs6_codes == ("731210",)


def test_los_capitulos_98_y_99_no_son_sistema_armonizado() -> None:
    assert hs6_de(("7323.93.0030", "9903.88.03", "9802.00.80", "7323.93.0080")) == ("732393",)


def test_la_url_es_la_publica_y_no_la_firmada_que_caduca() -> None:
    url = parse(_detalle()).url
    assert url == "https://rulings.cbp.gov/ruling/954053"
    assert "X-Amz" not in url


def test_el_texto_pasa_de_retornos_a_saltos_sin_perder_contenido() -> None:
    texto = parse(_detalle()).full_text
    assert "\r" not in texto
    assert texto.startswith("HQ 954053")
    assert "TARIFF NO.:  7312.10.10" in texto


def test_una_revocada_lo_dice() -> None:
    r = parse(_detalle(revokedBy=["H123456"]))
    assert r.is_revoked and r.revoked_by == ("H123456",)
    assert parse(_detalle(operationallyRevoked=True)).is_revoked


def test_la_revocacion_que_el_detalle_no_trae_se_toma_de_la_busqueda() -> None:
    """HQ 087732: revocada por 950390 según la búsqueda; `null` en el detalle."""
    detalle = _detalle(revokedBy=None)
    resumen = {"rulingNumber": "954053", "revokedBy": ["950390"], "relatedRulings": ["1"]}
    r = parse(combinar(detalle, resumen))
    assert r.is_revoked and r.revoked_by == ("950390",)
    assert r.related_rulings == ("1",)


def test_lo_que_trae_el_detalle_no_se_pisa() -> None:
    r = parse(combinar(_detalle(revokedBy=["H1"]), {"revokedBy": ["H2"]}))
    assert r.revoked_by == ("H1",)


def test_sin_texto_no_se_carga() -> None:
    with pytest.raises(ResolucionIlegibleError):
        parse(_detalle(text="  "))


def test_la_busqueda_por_partida_se_filtra_por_codigo() -> None:
    """Buscar «7615» devuelve también resoluciones que sólo la mencionan."""
    assert de_la_partida({"tariffs": "7615.10.7180"}, "7615")
    assert not de_la_partida({"tariffs": "7321.11.10"}, "7615")
    assert not de_la_partida({"tariffs": ""}, "7615")


@pytest.mark.integration
def test_la_carga_inserta_y_luego_solo_actualiza_el_estado(
    pg_session: Session,  # noqa: F811
) -> None:
    import sqlalchemy as sa
    from database.models import ComparableRuling
    from ingestion.cbp_cross.load import cargar

    pg_session.execute(
        sa.delete(ComparableRuling).where(ComparableRuling.ruling_number == "954053")
    )
    assert cargar(pg_session, parse(_detalle()), content_hash="0" * 64, minio_key="cbp/x.json")
    pg_session.flush()
    assert not cargar(
        pg_session,
        parse(_detalle(revokedBy=["H123456"])),
        content_hash="0" * 64,
        minio_key="cbp/x.json",
    )
    pg_session.flush()
    fila = pg_session.scalars(
        sa.select(ComparableRuling).where(ComparableRuling.ruling_number == "954053")
    ).one()
    assert fila.data_origin == "PUBLIC"
    assert fila.is_revoked and fila.revoked_by == ["H123456"]
    assert fila.hs6_codes == ["731210"]
    assert fila.valid_from == date(1993, 6, 30)
