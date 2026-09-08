"""Tests del endpoint que crea decisiones.

Es el único que escribe, y el que convierte el sistema en algo que se puede
enseñar: hasta ahora todas las pantallas leían un caso precargado.

Los tests del catálogo son los que más importan: la tarifa real tiene
versiones solapadas del mismo código —`84713001` tiene una que venció en
2022 y otra vigente— y clasificar con la equivocada da un resultado que
parece correcto y no lo es (§14).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from database.models import LegalDocument, LegalRule, TariffFraction
from database.repositories.notes import LegalNotesRepository
from database.repositories.tariff import MAX_CANDIDATOS, TariffCatalogRepository
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

FECHA = date(2026, 3, 15)


def _sql(sentencia: object) -> str:
    """La consulta compilada con sus valores, para poder afirmar sobre ella."""
    return " ".join(
        str(sentencia.compile(compile_kwargs={"literal_binds": True})).split()  # type: ignore[attr-defined]
    )


def _capturar(metodo: str, **kwargs: object) -> str:
    sesion = MagicMock()
    getattr(TariffCatalogRepository(sesion), metodo)(**kwargs)
    llamada = sesion.scalars.call_args or sesion.execute.call_args
    return _sql(llamada.args[0])


# ── La vigencia no es opcional ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metodo", "kwargs"),
    [
        ("headings", {"on_date": FECHA, "terms": ["laptop"]}),
        ("subheadings", {"on_date": FECHA, "heading": "8471"}),
        ("fractions", {"on_date": FECHA, "subheading": "847130"}),
    ],
)
def test_toda_consulta_filtra_por_vigencia(metodo: str, kwargs: dict) -> None:
    """EL TEST QUE IMPORTA.

    La tarifa tiene versiones solapadas del mismo código. Sin el filtro, una
    operación de 2024 podría clasificarse con la tarifa de 2026.
    """
    sql = _capturar(metodo, **kwargs)

    assert "valid_from <= '2026-03-15'" in sql
    assert "valid_to IS NULL" in sql
    assert "valid_to >= '2026-03-15'" in sql


def test_el_filtro_se_aplica_en_sql_no_despues() -> None:
    """Si se trajeran todas las versiones y se descartaran en Python,
    cualquier consulta que olvidara el paso devolvería la fila incorrecta.

    Se mira la cláusula WHERE y no la sentencia entera: `valid_from` también
    aparece en la lista de columnas del SELECT, así que buscarlo en todo el
    SQL no probaría nada.
    """
    sql = _capturar("fractions", on_date=FECHA, subheading="847130")
    where = sql.split("WHERE", 1)[1]

    assert "valid_from <= '2026-03-15'" in where
    assert "valid_to" in where


@pytest.mark.parametrize(
    ("metodo", "kwargs"),
    [
        ("headings", {"on_date": FECHA, "terms": ["x"]}),
        ("subheadings", {"on_date": FECHA, "heading": "8471"}),
        ("fractions", {"on_date": FECHA, "subheading": "847130"}),
    ],
)
def test_toda_consulta_esta_acotada(metodo: str, kwargs: dict) -> None:
    """Cien partidas no ayudan a decidir: hacen la traza ilegible."""
    assert f"LIMIT {MAX_CANDIDATOS}" in _capturar(metodo, **kwargs)


def test_las_fracciones_salen_de_la_tabla_correcta() -> None:
    sql = _capturar("fractions", on_date=FECHA, subheading="847130")

    assert "regulatory.tariff_fractions" in sql
    assert "subheading = '847130'" in sql


def test_ordena_por_especificidad() -> None:
    """La RGI 3 a) prefiere la partida más específica."""
    assert "specificity DESC" in _capturar("fractions", on_date=FECHA, subheading="847130")


# ── Notas legales: hoy no hay corpus, y se dice ─────────────────────────────


def test_las_notas_tambien_filtran_por_vigencia() -> None:
    """Nunca una norma posterior a la operación (§14)."""
    sesion = MagicMock()
    LegalNotesRepository(sesion).notes_for(on_date=FECHA, chapter="84")

    sql = _sql(sesion.scalars.call_args.args[0])
    assert "valid_from <= '2026-03-15'" in sql
    assert "regulatory.legal_rules" in sql


def test_hay_corpus_distingue_vacio_de_no_consultado() -> None:
    """Sin notas, una clasificación es menos fundamentada — y hay que decirlo.

    La RGI 1 se determina por los textos de las partidas Y por las notas.
    Devolver «no excluye» sin haberlas consultado sería mentir por omisión.
    """
    sesion = MagicMock()
    sesion.scalar.return_value = 0

    assert LegalNotesRepository(sesion).hay_corpus(on_date=FECHA) is False

    sesion.scalar.return_value = 12
    assert LegalNotesRepository(sesion).hay_corpus(on_date=FECHA) is True


def test_sin_terminos_no_hay_exclusion_inventada() -> None:
    """Sin con qué buscar, no se afirma que algo excluya."""
    assert (
        LegalNotesRepository(MagicMock()).excludes(on_date=FECHA, heading="8471", terms=[]) is None
    )


# ── Contrato con el motor ───────────────────────────────────────────────────


def test_los_repositorios_cumplen_los_puertos_del_motor() -> None:
    """Si un puerto cambia, esto falla antes de que falle una clasificación."""
    from core.rgi_engine.ports import LegalNotes, TariffCatalog

    assert isinstance(TariffCatalogRepository(MagicMock()), TariffCatalog)
    assert isinstance(LegalNotesRepository(MagicMock()), LegalNotes)


def test_las_columnas_usadas_existen() -> None:
    """Evita el fallo que tuve: asumir `rule_type` y `scope_code`, que no existen."""
    columnas_regla = {c.name for c in LegalRule.__table__.columns}
    columnas_fraccion = {c.name for c in TariffFraction.__table__.columns}

    assert {"path", "rule_number", "text", "valid_from", "valid_to"} <= columnas_regla
    assert {"code", "heading", "subheading", "specificity"} <= columnas_fraccion


def test_el_codigo_viaja_como_texto() -> None:
    """Los ceros a la izquierda son significativos: 08471301 ≠ 8471301."""
    assert isinstance(TariffFraction.__table__.c.code.type, sa.String)


# ── Notas legales: no contaminadas por otros documentos (integración) ──────


@pytest.fixture
def pg_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Sesión contra el Postgres local. Salta el test si no hay conexión.

    Ver `tests/test_canonical_model.py::pg_session` — mismo patrón: deshace
    el aislamiento de `_isolated_env` sólo para esta sesión, y cada test corre
    en una transacción que se revierte al final.
    """
    from apps.api.config import get_settings

    monkeypatch.setenv("ADUANERO_ENV_FILE", ".env")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    engine = sa.create_engine(get_settings().sqlalchemy_url)
    try:
        conn = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"sin PostgreSQL local: {exc}")
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()
        engine.dispose()
        get_settings.cache_clear()


def _legal_document(*, kind: str, short_name: str) -> LegalDocument:
    return LegalDocument(
        title=short_name,
        short_name=short_name,
        kind=kind,
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _legal_rule(*, document: LegalDocument, rule_number: str, path: str | None, text: str) -> LegalRule:
    return LegalRule(
        legal_document_id=document.id,
        rule_number=rule_number,
        path=path,
        text=text,
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.integration
def test_notes_for_no_mezcla_articulos_de_otro_documento(pg_session: Session) -> None:
    """Regresión real (Task 4, 2026-09-08): con la Ley Aduanera cargada,
    `notes_for(chapter="84")` devolvía también sus artículos 84 y 84-A —que
    no son notas de capítulo arancelario— porque `rule_number.startswith`
    no distinguía de qué documento venía cada fila. Se acota a
    `LegalDocument.kind == "TARIFF"`, que es como se registra la LIGIE."""
    tarifa = _legal_document(kind="TARIFF", short_name="LIGIE_PRUEBA_NOTES")
    ley = _legal_document(kind="LAW", short_name="LEY_PRUEBA_NOTES")
    pg_session.add_all([tarifa, ley])
    pg_session.flush()

    pg_session.add_all(
        [
            _legal_rule(
                document=tarifa,
                rule_number="NOTAS-CAP-84",
                path="Capítulo 84",
                text="Nota real del capítulo arancelario 84.",
            ),
            _legal_rule(
                document=ley,
                rule_number="84",
                path=None,
                text="Artículo 84 de la Ley Aduanera, sin relación con el capítulo 84.",
            ),
            _legal_rule(
                document=ley,
                rule_number="84A",
                path=None,
                text="Artículo 84-A de la Ley Aduanera.",
            ),
        ]
    )
    pg_session.flush()

    resultados = LegalNotesRepository(pg_session).notes_for(on_date=FECHA, chapter="84")

    assert any("Nota real del capítulo arancelario 84" in r for r in resultados)
    assert not any("Ley Aduanera" in r for r in resultados)
