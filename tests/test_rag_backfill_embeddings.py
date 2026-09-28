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
from core.llm.errors import ProviderResponseError
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


def test_backfill_confirma_con_commit_no_con_flush() -> None:
    """EL TEST QUE IMPORTA (hallazgo real de Ulises, 2026-09-09): `flush()`
    manda el UPDATE pero no lo hace durable. Si `provider.embed()` lanza más
    adelante y nadie más confirma, `Session.__exit__` cierra sin commitear y
    hasta lo ya enviado se revierte — pagado a OpenAI, cero persistido, y el
    reintento vuelve a pagar por lo mismo."""
    sesion = MagicMock()
    sesion.scalars.return_value.all.return_value = [_chunk(embedding=None)]

    backfill(sesion, provider=_ProveedorDeMentira())  # type: ignore[arg-type]

    sesion.commit.assert_called()
    sesion.flush.assert_not_called()


def test_backfill_confirma_cada_commit_every_no_solo_al_final() -> None:
    sesion = MagicMock()
    sesion.scalars.return_value.all.return_value = [_chunk(embedding=None) for _ in range(5)]

    backfill(sesion, provider=_ProveedorDeMentira(), commit_every=2)  # type: ignore[arg-type]

    # 2 checkpoints (en 2 y en 4) + el commit final tras el 5: 3 en total.
    assert sesion.commit.call_count == 3


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


class _ProveedorQueFallaAMitad:
    """Simula un 429 a media corrida: las primeras llamadas responden bien,
    luego truena — igual que reportó Ulises con OpenAI."""

    def __init__(self, *, falla_en: int) -> None:
        self._falla_en = falla_en
        self.llamadas = 0

    def embed(self, text: str) -> list[float]:
        self.llamadas += 1
        if self.llamadas == self._falla_en:
            raise RuntimeError("429 Too Many Requests")
        return _VECTOR_DE_MENTIRA


@pytest.mark.integration
def test_backfill_conserva_lo_confirmado_si_falla_a_mitad(pg_session: sa.orm.Session) -> None:  # noqa: F811
    """EL TEST QUE PIDIÓ ULISES: una corrida interrumpida no debe perder lo
    que ya vectorizó y pagó. Con `commit_every=2` y un fallo en la 3a
    llamada, las primeras 2 filas quedan durables aunque la corrida truene
    y nadie llame `session.commit()` después."""
    from database.models import LegalChunkRecord, LegalDocument
    from database.repositories.chunks import PostgresChunkStore
    from rag.types import LegalChunk

    doc = LegalDocument(
        title="Ley de prueba (backfill, fallo a mitad)",
        short_name="LEY_PRUEBA_BACKFILL_FALLA",
        kind="LAW",
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    pg_session.add(doc)
    pg_session.flush()

    # `backfill()` es global a propósito (cualquier chunk sin vectorizar, de
    # cualquier documento): la base ya trae el corpus real de esta sesión
    # con `embedding IS NULL`. Se marca ese ambiente como ya vectorizado
    # SÓLO dentro de esta transacción, para que el fallo a la 3a llamada
    # caiga de verdad sobre las 5 filas de esta prueba y no sobre las 366
    # reales que llegarían primero. `pg_session` revierte todo al final.
    pg_session.execute(
        sa.update(LegalChunkRecord)
        .where(LegalChunkRecord.embedding.is_(None))
        .values(embedding=_VECTOR_DE_MENTIRA)
    )

    store = PostgresChunkStore(pg_session)
    store.add(
        [
            LegalChunk(
                document_id=doc.id,
                document=doc.title,
                article=str(i),
                text=f"texto {i}",
                content_hash=f"h{i}",
                data_origin="OFFICIAL",
                valid_from=date(2020, 1, 1),
                url="https://x",
            )
            for i in range(1, 6)
        ]
    )

    proveedor = _ProveedorQueFallaAMitad(falla_en=3)
    with pytest.raises(RuntimeError, match="429"):
        backfill(pg_session, provider=proveedor, commit_every=2)

    # Sin ningún rollback/commit explícito después del fallo: lo que ya
    # confirmó el checkpoint de `commit_every=2` tiene que seguir ahí.
    filas = pg_session.scalars(
        sa.select(LegalChunkRecord).where(LegalChunkRecord.legal_document_id == doc.id)
    ).all()
    assert sum(1 for f in filas if f.embedding is not None) == 2
    assert sum(1 for f in filas if f.embedding is None) == 3


# ── Un chunk que no cabe no tumba la carga (Persona 1, 28-sep) ─────────────


class _ProveedorConUnTextoQueNoCabe:
    """Rechaza un texto concreto como lo hace OpenAI: HTTP 400 genérico."""

    default_embedding_model = "fake-embedding"

    def __init__(self, rechaza: str) -> None:
        self._rechaza = rechaza
        self.llamadas: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.llamadas.append(text)
        if text == self._rechaza:
            raise ProviderResponseError(
                "openai: HTTP 400 — Invalid 'input': maximum context length is 8192 tokens."
            )
        return _VECTOR_DE_MENTIRA


def test_un_chunk_demasiado_largo_no_impide_vectorizar_los_demas() -> None:
    """537 reglas de las RGCE se quedaron sin vector por 3 que no caben.

    La regla 7.3.3 mide 46 094 caracteres. Con la excepción propagándose, un
    solo chunk largo dejaba las otras 534 sin vectorizar — e invisibles para
    la búsqueda semántica del Copilot.
    """
    sesion = MagicMock()
    largo, corto = _chunk(embedding=None), _chunk(embedding=None)
    largo.text = "x" * 46094
    sesion.scalars.return_value.all.return_value = [largo, corto]

    tocados = backfill(sesion, provider=_ProveedorConUnTextoQueNoCabe(largo.text))  # type: ignore[arg-type]

    assert tocados == 1, "el corto sí se vectorizó"
    assert corto.embedding == _VECTOR_DE_MENTIRA
    assert largo.embedding is None, "el largo se salta, no se trunca"


def test_un_fallo_que_no_sea_de_longitud_si_tumba_la_corrida() -> None:
    """Un 429 o una llave inválida tienen que parar: reintentar 500 chunks
    contra un proveedor que no responde es pagar por nada."""

    class _ProveedorCaido:
        default_embedding_model = "fake-embedding"

        def embed(self, text: str) -> list[float]:
            raise ProviderResponseError("openai: HTTP 429 — rate limit exceeded")

    sesion = MagicMock()
    sesion.scalars.return_value.all.return_value = [_chunk(embedding=None)]

    with pytest.raises(ProviderResponseError):
        backfill(sesion, provider=_ProveedorCaido())  # type: ignore[arg-type]
