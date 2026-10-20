"""El grafo en la búsqueda jurídica (§27): texto + vector + grafo.

Lo que se fija aquí:

1. el grafo devuelve IDS de reglas, y el texto sale del almacén con su vigencia;
2. lo que el grafo sugiere y no rige ese día no entra;
3. si el grafo no responde, la búsqueda sigue y lo dice;
4. una sugerencia dice de cuándo es el grafo que la dio.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from database.repositories.chunks import PostgresChunkStore
from graph.busqueda import ExpansorDelGrafo, fracciones_de
from neo4j.exceptions import ServiceUnavailable
from rag import MemoriaChunkStore, recuperar
from rag.types import LegalChunk

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

pytestmark = pytest.mark.unit

FECHA = date(2024, 3, 15)
REGLA_54 = str(uuid.uuid4())
REGLA_DEROGADA = str(uuid.uuid4())


def _chunk(article: str, text: str, *, regla: str | None = None, **over: Any) -> LegalChunk:
    campos: dict[str, Any] = {
        "document_id": uuid.uuid4(),
        "document": "Ley Aduanera",
        "article": article,
        "text": text,
        "content_hash": f"h-{article}",
        "data_origin": "OFFICIAL",
        "valid_from": date(2020, 1, 1),
        "url": "https://dof.gob.mx/x",
        "legal_rule_id": uuid.UUID(regla) if regla else None,
    }
    campos.update(over)
    return LegalChunk(**campos)


class GrafoFalso:
    """Un `Consultable` que contesta las dos consultas del expansor."""

    def __init__(self, ids: list[str], *, at: str | None = "2026-10-13T22:00:00+00:00") -> None:
        self.ids = ids
        self.at = at
        self.consultas: list[dict[str, Any]] = []

    def consultar(self, cypher: str, **parametros: Any) -> list[dict[str, Any]]:
        self.consultas.append(parametros)
        if "Proyeccion" in cypher:
            return [{"at": self.at}] if self.at else []
        return [{"id": i, "decisiones": 3} for i in self.ids]


class GrafoCaido:
    def consultar(self, cypher: str, **parametros: Any) -> list[dict[str, Any]]:
        raise ServiceUnavailable("neo4j no responde")


def _almacen() -> MemoriaChunkStore:
    almacen = MemoriaChunkStore()
    almacen.add(
        [
            _chunk("54", "El agente aduanal responde de la clasificación.", regla=REGLA_54),
            _chunk(
                "35-B",
                "Texto que ya no rige.",
                regla=REGLA_DEROGADA,
                valid_to=date(2021, 12, 31),
            ),
            _chunk("58", "Las obligaciones del importador sobre el valor."),
        ]
    )
    return almacen


# ── Qué se le pregunta al grafo ─────────────────────────────────────────────


def test_reconoce_la_fraccion_con_y_sin_puntos() -> None:
    assert fracciones_de("¿qué sostiene la 7312.10.05 y la 73121008?") == [
        "73121005",
        "73121008",
    ]


def test_sin_fraccion_no_se_consulta_el_grafo() -> None:
    grafo = GrafoFalso([REGLA_54])
    expansor = ExpansorDelGrafo(grafo)

    assert expansor.reglas_relacionadas("valor en aduana", on_date=FECHA, limit=3) == []
    assert grafo.consultas == []
    assert expansor.nota is not None and "no nombra ninguna fracción" in expansor.nota


def test_la_consulta_lleva_la_fecha_de_la_operacion() -> None:
    """§14: la versión de la fracción que regía ese día, no la de hoy."""
    grafo = GrafoFalso([REGLA_54])
    ExpansorDelGrafo(grafo).reglas_relacionadas("la 73121005", on_date=FECHA, limit=3)

    assert grafo.consultas[0]["fecha"] == "2024-03-15"
    assert grafo.consultas[0]["codigos"] == ["73121005"]


def test_la_nota_dice_de_cuando_es_el_grafo() -> None:
    expansor = ExpansorDelGrafo(GrafoFalso([REGLA_54]))
    expansor.reglas_relacionadas("la 73121005", on_date=FECHA, limit=3)

    assert expansor.nota is not None
    assert "1 regla" in expansor.nota and "el 2026-10-13" in expansor.nota


def test_si_el_grafo_no_responde_se_dice_y_no_tumba_nada() -> None:
    expansor = ExpansorDelGrafo(GrafoCaido())  # type: ignore[arg-type]

    assert expansor.reglas_relacionadas("la 73121005", on_date=FECHA, limit=3) == []
    assert expansor.nota is not None and "ServiceUnavailable" in expansor.nota


# ── Qué hace la recuperación con lo que sugiere ─────────────────────────────


def test_lo_que_sugiere_el_grafo_va_delante_y_se_marca() -> None:
    r = recuperar(
        "importador valor 73121005",
        on_date=FECHA,
        store=_almacen(),
        expansor=ExpansorDelGrafo(GrafoFalso([REGLA_54])),
    )

    assert r.chunks[0].article == "54", "lo del grafo, primero"
    assert r.via_grafo == ("h-54",)
    assert r.grafo is not None and "sugirió" in r.grafo


def test_lo_sugerido_que_no_rige_ese_dia_no_entra() -> None:
    """El grafo dice dónde mirar; la vigencia la sigue decidiendo el almacén."""
    r = recuperar(
        "73121005",
        on_date=FECHA,
        store=_almacen(),
        expansor=ExpansorDelGrafo(GrafoFalso([REGLA_DEROGADA])),
    )

    assert "35-B" not in [c.article for c in r.chunks]
    assert r.via_grafo == ()


def test_lo_del_grafo_no_se_repite_si_la_busqueda_ya_lo_traia() -> None:
    r = recuperar(
        "agente aduanal clasificación 73121005",
        on_date=FECHA,
        store=_almacen(),
        expansor=ExpansorDelGrafo(GrafoFalso([REGLA_54])),
    )

    articulos = [c.article for c in r.chunks]
    assert articulos.count("54") == 1


def test_el_grafo_ocupa_como_mucho_un_tercio() -> None:
    almacen = MemoriaChunkStore()
    reglas = [str(uuid.uuid4()) for _ in range(5)]
    almacen.add([_chunk(f"A{i}", "texto", regla=r) for i, r in enumerate(reglas)])

    r = recuperar(
        "73121005",
        on_date=FECHA,
        store=almacen,
        limit=6,
        expansor=ExpansorDelGrafo(GrafoFalso(reglas)),
    )

    assert len(r.via_grafo) == 2


def test_sin_expansor_la_recuperacion_no_cambia() -> None:
    r = recuperar("importador valor", on_date=FECHA, store=_almacen())
    assert r.via_grafo == ()
    assert r.grafo is None


# ── El almacén de verdad, contra Postgres ───────────────────────────────────


def test_un_id_que_no_es_uuid_no_llega_a_sql() -> None:
    from unittest.mock import MagicMock

    sesion = MagicMock()
    assert PostgresChunkStore(sesion).por_reglas(["no-es-un-uuid"], on_date=FECHA) == []
    sesion.execute.assert_not_called()


@pytest.mark.integration
def test_por_reglas_lee_los_chunks_vigentes_de_esa_regla(
    pg_session: sa.orm.Session,  # noqa: F811
) -> None:
    from database.models import LegalDocument, LegalRule

    momento = datetime(2026, 1, 1, tzinfo=UTC)
    doc = LegalDocument(
        title="Ley de prueba (por_reglas)",
        short_name="LEY_PRUEBA_POR_REGLAS",
        kind="LAW",
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=momento,
    )
    pg_session.add(doc)
    pg_session.flush()
    regla = LegalRule(
        legal_document_id=doc.id,
        rule_number="7",
        text="Texto de la norma.",
        data_origin="OFFICIAL",
        valid_from=date(2020, 1, 1),
        source_url="https://x",
        content_hash="h",
        retrieved_at=momento,
    )
    pg_session.add(regla)
    pg_session.flush()

    store = PostgresChunkStore(pg_session)
    store.add(
        [
            _chunk(
                "7",
                "Lo que dice el artículo 7.",
                document_id=doc.id,
                content_hash="h-por-reglas",
                valid_from=date(2020, 1, 1),
            )
        ]
    )

    [chunk] = store.por_reglas([str(regla.id)], on_date=FECHA)
    assert chunk.article == "7"
    assert chunk.legal_rule_id == regla.id
    assert store.por_reglas([str(regla.id)], on_date=date(2019, 1, 1)) == [], "no regía"
