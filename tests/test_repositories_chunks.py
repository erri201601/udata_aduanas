"""Tests de `PostgresChunkStore` (§27, PR #45 de Persona 3).

`unit` — el filtro de vigencia/procedencia se inspecciona en el SQL compilado,
igual que en `test_classify_endpoint.py`: mirar el resultado no probaría que
el filtro se aplicó en la base y no después en Python.
`integration` — contra PostgreSQL real: que el `UniqueConstraint` rechace una
recarga y que el índice HNSW de verdad ordene por similitud de coseno.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from database.repositories.chunks import ChunkPersistError, PostgresChunkStore
from rag.types import LegalChunk

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

pytestmark = pytest.mark.unit

FECHA = date(2026, 3, 15)


def _chunk(**over: object) -> LegalChunk:
    base = {
        "document_id": "11111111-1111-1111-1111-111111111111",
        "document": "Ley Aduanera",
        "article": "36-A",
        "text": "Texto del artículo.",
        "content_hash": "sha256:x",
        "data_origin": "OFFICIAL",
        "valid_from": date(2018, 6, 25),
        "url": "https://www.diputados.gob.mx/LeyesBiblio/pdf/LAdua.pdf",
    }
    base.update(over)
    return LegalChunk(**base)  # type: ignore[arg-type]


def _sql(sentencia: object) -> str:
    return " ".join(
        str(sentencia.compile(compile_kwargs={"literal_binds": True})).split()  # type: ignore[attr-defined]
    )


def _capturar_search(**kwargs: object) -> str:
    sesion = MagicMock()
    PostgresChunkStore(sesion).search(**kwargs)  # type: ignore[arg-type]
    return _sql(sesion.execute.call_args.args[0])


# ── Puerto ───────────────────────────────────────────────────────────────────


def test_cumple_el_puerto_chunkstore() -> None:
    from rag.ports import ChunkStore

    assert isinstance(PostgresChunkStore(MagicMock()), ChunkStore)


# ── Vigencia y procedencia van en el WHERE, antes de puntuar ─────────────────


def test_search_filtra_por_vigencia() -> None:
    sql = _capturar_search(on_date=FECHA)
    assert "valid_from <= '2026-03-15'" in sql
    assert "valid_to IS NULL" in sql
    assert "valid_to >= '2026-03-15'" in sql


def test_search_solo_fundamentables_por_defecto() -> None:
    sql = _capturar_search(on_date=FECHA)
    assert "data_origin IN" in sql
    for origen in ("OFFICIAL", "LICENSED", "HUMAN_VALIDATED"):
        assert f"'{origen}'" in sql
    assert "'SYNTHETIC'" not in sql


def test_search_permite_no_fundamentables_explicito() -> None:
    sql = _capturar_search(on_date=FECHA, solo_fundamentables=False)
    assert "data_origin IN" not in sql


def test_search_con_embedding_ordena_por_coseno_y_excluye_sin_vector() -> None:
    sql = _capturar_search(on_date=FECHA, query_embedding=[0.1, 0.2, 0.3])
    assert "embedding IS NOT NULL" in sql
    assert "<=>" in sql  # operador de distancia coseno de pgvector


def test_search_sin_embedding_filtra_por_termino() -> None:
    # `_sql()` compila sin dialecto: `.ilike()` sale como `lower(x) LIKE lower(y)`.
    # Contra PostgreSQL real (ver el test de integración) sí es un ILIKE nativo.
    sql = _capturar_search(on_date=FECHA, terms=["portátil", "laptop"])
    assert "lower('%portátil%')" in sql
    assert "lower('%laptop%')" in sql


def test_search_esta_acotado() -> None:
    assert "LIMIT 3" in _capturar_search(on_date=FECHA, limit=3)


# ── add() no inventa lo que RegulatoryMixin exige ────────────────────────────


def test_add_rechaza_chunk_sin_document_id() -> None:
    with pytest.raises(ChunkPersistError, match="document_id"):
        PostgresChunkStore(MagicMock()).add([_chunk(document_id=None)])


def test_add_rechaza_chunk_sin_url() -> None:
    with pytest.raises(ChunkPersistError, match="url"):
        PostgresChunkStore(MagicMock()).add([_chunk(url=None)])


def test_add_devuelve_cuantos_entraron() -> None:
    sesion = MagicMock()
    n = PostgresChunkStore(sesion).add([_chunk(), _chunk(article="36-A fracción I")])
    assert n == 2
    sesion.flush.assert_called_once()


# ── Integración: la tabla y sus índices existen de verdad ────────────────────


@pytest.mark.integration
def test_add_y_search_ida_y_vuelta(pg_session: sa.orm.Session) -> None:  # noqa: F811
    from database.models import LegalDocument

    doc = LegalDocument(
        title="Ley de prueba (chunks)",
        short_name="LEY_PRUEBA_CHUNKS",
        kind="LAW",
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pg_session.add(doc)
    pg_session.flush()

    store = PostgresChunkStore(pg_session)
    n = store.add(
        [
            _chunk(document_id=doc.id, article="1", valid_from=date(2020, 1, 1)),
            _chunk(
                document_id=doc.id,
                article="2",
                valid_from=date(2020, 1, 1),
                data_origin="SYNTHETIC",
            ),
        ]
    )
    assert n == 2

    # `limit` alto a propósito: la base ya trae el corpus real cargado esta
    # sesión (274 artículos de la Ley Aduanera), y el default de 10 los
    # ordenaría por delante de estas dos filas de prueba de 2020.
    encontrados = store.search(on_date=FECHA, solo_fundamentables=True, limit=10_000)
    articulos = {c.article for c in encontrados if c.document_id == doc.id}
    assert "1" in articulos
    assert "2" not in articulos  # SYNTHETIC no fundamenta


@pytest.mark.integration
def test_recarga_del_mismo_articulo_no_duplica_en_silencio(
    pg_session: sa.orm.Session,  # noqa: F811
) -> None:
    from database.models import LegalDocument

    doc = LegalDocument(
        title="Ley de prueba (chunks dup)",
        short_name="LEY_PRUEBA_CHUNKS_DUP",
        kind="LAW",
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pg_session.add(doc)
    pg_session.flush()

    store = PostgresChunkStore(pg_session)
    store.add([_chunk(document_id=doc.id, article="1", valid_from=date(2020, 1, 1))])

    with pytest.raises(sa.exc.IntegrityError, match="uq_legal_chunks_document_article_valid_from"):
        store.add([_chunk(document_id=doc.id, article="1", valid_from=date(2020, 1, 1))])


@pytest.mark.integration
def test_search_por_embedding_ordena_por_similitud_real(pg_session: sa.orm.Session) -> None:  # noqa: F811
    """El índice HNSW existe y `<=>` de verdad ordena por coseno, no por azar."""
    from database.models import LegalDocument

    doc = LegalDocument(
        title="Ley de prueba (embeddings)",
        short_name="LEY_PRUEBA_EMBED",
        kind="LAW",
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pg_session.add(doc)
    pg_session.flush()

    dim = 1536
    lejano = [0.0] * dim
    lejano[0] = 1.0
    cercano = [0.0] * dim
    cercano[1] = 1.0

    store = PostgresChunkStore(pg_session)
    store.add(
        [
            _chunk(
                document_id=doc.id,
                article="LEJANO",
                valid_from=date(2020, 1, 1),
                embedding=lejano,
            ),
            _chunk(
                document_id=doc.id,
                article="CERCANO",
                valid_from=date(2020, 1, 1),
                embedding=cercano,
            ),
        ]
    )

    consulta = [0.0] * dim
    consulta[1] = 0.9  # casi idéntico a "cercano"
    resultado = store.search(on_date=FECHA, query_embedding=consulta, limit=2)
    propios = [c for c in resultado if c.document_id == doc.id]
    assert propios[0].article == "CERCANO"
