"""Tests de `rag.backfill_embeddings` (§27).

`unit` — `backfill()` con sesión y proveedor de mentira: no toca la red ni
Postgres.
`integration` — contra Postgres real, con un proveedor de mentira (nunca una
llave real ni una llamada HTTP de verdad).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from database.models.regulatory import EMBEDDING_DIM
from rag.backfill_embeddings import _database_url, backfill, main

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

pytestmark = pytest.mark.unit

#: `regulatory.legal_chunks.embedding` es `vector(1536)`: Postgres rechaza
#: cualquier otro ancho, así que el vector de mentira tiene que ser de este
#: mismo tamaño para el test de integración (no para los `unit`, que usan
#: MagicMock y nunca llegan a la base).
_VECTOR_DE_MENTIRA = [0.1, 0.2, 0.3, *([0.0] * (EMBEDDING_DIM - 3))]


class _ProveedorDeMentira:
    default_embedding_model = "fake-embedding"

    def __init__(self) -> None:
        self.llamadas: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.llamadas.append(text)
        return _VECTOR_DE_MENTIRA


def _chunk(*, embedding: list[float] | None) -> MagicMock:
    fila = MagicMock()
    fila.text = "texto del chunk"
    fila.embedding = embedding
    return fila


def test_backfill_solo_toca_los_sin_embedding() -> None:
    sesion = MagicMock()
    sin_vector = _chunk(embedding=None)
    sesion.scalars.return_value.all.return_value = [sin_vector]
    proveedor = _ProveedorDeMentira()

    n = backfill(sesion, provider=proveedor)  # type: ignore[arg-type]

    assert n == 1
    assert sin_vector.embedding == _VECTOR_DE_MENTIRA
    assert proveedor.llamadas == ["texto del chunk"]


def test_backfill_consulta_filtra_por_embedding_null() -> None:
    sesion = MagicMock()
    sesion.scalars.return_value.all.return_value = []

    backfill(sesion, provider=_ProveedorDeMentira())  # type: ignore[arg-type]

    sql = str(sesion.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "embedding IS NULL" in sql


def test_backfill_hace_flush_al_final() -> None:
    sesion = MagicMock()
    sesion.scalars.return_value.all.return_value = [_chunk(embedding=None)]

    backfill(sesion, provider=_ProveedorDeMentira())  # type: ignore[arg-type]

    sesion.flush.assert_called()


def test_main_pide_openai_explicito_no_el_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """EL TEST QUE IMPORTA: `DEFAULT_MODEL_PROVIDER` puede ser `anthropic`, que
    no tiene embeddings. `main()` debe pedir `openai` por nombre, nunca
    `get_default_provider()` — si lo hiciera, `build_provider` se llamaría
    sin `name` y este test lo detecta."""
    capturado: dict[str, object] = {}

    def _build_provider_falso(*, name: str | None = None, **kwargs: object) -> _ProveedorDeMentira:
        capturado["name"] = name
        return _ProveedorDeMentira()

    contexto = MagicMock()
    contexto.__enter__.return_value = contexto
    contexto.__exit__.return_value = None

    monkeypatch.setattr("rag.backfill_embeddings.build_provider", _build_provider_falso)
    monkeypatch.setattr("rag.backfill_embeddings.backfill", lambda *a, **kw: 0)
    monkeypatch.setattr("rag.backfill_embeddings.create_engine", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("rag.backfill_embeddings.Session", lambda *a, **kw: contexto)

    main(["--target", "local"])

    assert capturado["name"] == "openai"


def test_target_shared_exige_variable_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADUANERO_SHARED_URL", raising=False)

    with pytest.raises(SystemExit, match="ADUANERO_SHARED_URL"):
        _database_url("shared")


@pytest.mark.integration
def test_backfill_ida_y_vuelta_contra_postgres(pg_session: sa.orm.Session) -> None:  # noqa: F811
    from database.models import LegalChunkRecord, LegalDocument
    from database.repositories.chunks import PostgresChunkStore
    from rag.types import LegalChunk

    doc = LegalDocument(
        title="Ley de prueba (backfill)",
        short_name="LEY_PRUEBA_BACKFILL",
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
    store.add(
        [
            LegalChunk(
                document_id=doc.id,
                document=doc.title,
                article="1",
                text="texto sin vectorizar",
                content_hash="h1",
                data_origin="OFFICIAL",
                valid_from=date(2020, 1, 1),
                url="https://x",
            )
        ]
    )

    # No se afirma nada sobre el total devuelto: la base ya trae el corpus
    # real cargado esta sesión, con `embedding IS NULL` en sus 274 filas —
    # `backfill()` es global a propósito (cualquier chunk sin vectorizar,
    # de cualquier documento), así que también las toca. La transacción de
    # `pg_session` se revierte al final: no deja rastro en la base local.
    backfill(pg_session, provider=_ProveedorDeMentira())

    fila = pg_session.scalars(sa.select(LegalChunkRecord).filter_by(legal_document_id=doc.id)).one()
    assert list(fila.embedding) == pytest.approx(_VECTOR_DE_MENTIRA)
