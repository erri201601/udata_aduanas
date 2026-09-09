"""Tests del Copilot.

LO QUE ESTOS TESTS PROTEGEN

1. Que NO redacte la respuesta. Parafrasear la ley es como se producen las
   citas inventadas; `redacta_respuesta` es una decisión, no una carencia, y
   un test la fija para que nadie la «mejore» sin discutirlo.
2. Que declare con qué buscó. Presentar una búsqueda por término como si
   fuera semántica vendería una capacidad que no está puesta.
3. Que sin fundamento lo diga con el mensaje literal, en vez de devolver
   pasajes que no sostienen nada.
4. Que el reordenamiento por términos casados funcione: sin él, un pasaje que
   casa 1 de 4 adelanta a uno que casa los 4 — comprobado contra el corpus
   real antes de escribirlo.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from apps.api.db import get_session
from apps.api.main import create_app
from fastapi.testclient import TestClient
from rag.types import LegalChunk

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

DOC = uuid.uuid4()


def _chunk(
    *,
    article: str,
    text: str,
    valid_from: date = date(2020, 1, 1),
    valid_to: date | None = None,
    data_origin: str = "OFFICIAL",
) -> LegalChunk:
    return LegalChunk(
        document_id=DOC,
        document="Ley Aduanera",
        article=article,
        text=text,
        content_hash=f"h{article}",
        data_origin=data_origin,
        valid_from=valid_from,
        valid_to=valid_to,
        url="https://dof.gob.mx/x",
    )


class SesionFalsa:
    """Sólo responde los dos conteos de cobertura del router."""

    def __init__(self, *, totales: int = 0, vectorizados: int = 0) -> None:
        self._valores = [totales, vectorizados]
        self._i = 0

    def scalar(self, _sentencia: Any) -> Any:
        valor = self._valores[self._i] if self._i < len(self._valores) else 0
        self._i += 1
        return valor


@contextmanager
def _cliente(
    chunks: list[LegalChunk] | None = None,
    *,
    embedder: Any = None,
    **cobertura: int,
) -> Iterator[TestClient]:
    """Cliente con el almacén en memoria en lugar del de Postgres.

    El parcheo se deshace al salir: dejarlo puesto contaminaría cualquier otro
    test que importe el router después, y ese es el tipo de fallo que aparece
    en CI y no en local, según el orden en que corran.
    """
    from rag import MemoriaChunkStore

    almacen = MemoriaChunkStore()
    if chunks:
        almacen.add(chunks)

    app = create_app()
    app.dependency_overrides[get_session] = lambda: SesionFalsa(**cobertura)

    # El router construye su propio PostgresChunkStore; se sustituye por el de
    # memoria para no necesitar Postgres en un test unitario.
    with (
        patch("apps.api.routers.copilot.PostgresChunkStore", lambda _s: almacen),
        patch("apps.api.routers.copilot.embedder_opcional", lambda: embedder),
        TestClient(app) as cliente,
    ):
        yield cliente


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    with _cliente(
        [
            _chunk(
                article="58",
                text="Las obligaciones del importador respecto del valor en aduana declarado.",
            ),
            _chunk(article="NOTAS-CAP-20", text="Notas del capítulo: el valor de las mercancías."),
        ],
        totales=366,
        vectorizados=0,
    ) as c:
        yield c


def _preguntar(cliente: TestClient, pregunta: str, **extra: Any) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {"pregunta": pregunta, "fecha": "2024-03-15"}
    cuerpo.update(extra)
    respuesta = cliente.post("/copilot/consultas", json=cuerpo)
    assert respuesta.status_code == 200, respuesta.text
    return dict(respuesta.json())


def test_el_copilot_responde(cliente: TestClient) -> None:
    assert _preguntar(cliente, "valor en aduana")["fecha"] == "2024-03-15"


def test_nunca_redacta_la_respuesta(cliente: TestClient) -> None:
    """EL TEST QUE IMPORTA.

    Parafrasear la ley es como se producen las citas inventadas. Que devuelva
    pasajes y no prosa es una decisión de diseño, no una limitación temporal.
    """
    d = _preguntar(cliente, "obligaciones del importador en el valor en aduana")

    assert d["redacta_respuesta"] is False
    assert "respuesta" not in d or not isinstance(d.get("respuesta"), str)
    assert d["pasajes"], "debería devolver pasajes"
    assert all("texto" in p and "cita" in p for p in d["pasajes"])


def test_declara_que_la_busqueda_no_es_semantica(cliente: TestClient) -> None:
    """Sin vectores, decir lo contrario vendería algo que no está puesto."""
    d = _preguntar(cliente, "valor en aduana")

    assert d["busqueda_semantica_disponible"] is False
    assert d["modo_busqueda"] == "TERMINO_Y_VIGENCIA"
    assert d["chunks_vectorizados"] == 0


def test_un_corpus_vectorizado_no_basta_para_decir_que_busca_por_significado() -> None:
    """EL FALLO QUE ESTO IMPIDE, Y QUE COMETÍ.

    La primera versión derivaba `modo_busqueda` de si el corpus tenía
    vectores. Cuando alguien corrió el backfill, la respuesta empezó a decir
    SEMANTICA mientras seguía buscando por coincidencia de palabra: ningún
    consumidor del RAG pasa todavía un embedder. El modo tiene que describir
    lo que se hizo, no lo que el corpus permitiría.
    """
    with _cliente(
        [_chunk(article="1", text="valor en aduana")], totales=366, vectorizados=366
    ) as c:
        d = _preguntar(c, "valor en aduana")

    assert d["chunks_vectorizados"] == 366, "el corpus sí está vectorizado"
    assert d["modo_busqueda"] == "TERMINO_Y_VIGENCIA", "pero así NO se buscó"
    assert d["busqueda_semantica_disponible"] is False


def test_ordena_por_terminos_casados_no_por_vigencia() -> None:
    """Sin esto, un pasaje que casa 1 de 4 adelanta al que casa los 4.

    Se reproduce el caso real: la nota de capítulo es MÁS reciente y casa
    sólo «valor»; el artículo 58 es más antiguo y casa los cuatro términos.
    """
    with _cliente(
        [
            _chunk(
                article="NOTAS-CAP-20",
                text="Notas del capítulo: el valor de las mercancías.",
                valid_from=date(2022, 6, 7),
            ),
            _chunk(
                article="58",
                text="Las obligaciones del importador respecto del valor en aduana.",
                valid_from=date(2013, 12, 9),
            ),
        ],
        totales=2,
    ) as c:
        d = _preguntar(c, "obligaciones del importador en el valor en aduana")

    assert d["pasajes"][0]["articulo"] == "58"
    assert d["pasajes"][0]["terminos_coincidentes"] == [
        "obligaciones",
        "importador",
        "valor",
        "aduana",
    ]


def test_enseña_con_que_terminos_busco(cliente: TestClient) -> None:
    d = _preguntar(cliente, "obligaciones del importador")

    # «del» es palabra vacía y no cuenta como término de búsqueda.
    assert d["terminos_buscados"] == ["obligaciones", "importador"]


def test_sin_fundamento_lo_dice_con_el_mensaje_literal() -> None:
    """«No tengo evidencia» es una respuesta correcta, no un fallo."""
    with _cliente([], totales=366) as c:
        d = _preguntar(c, "zzzz qwerty asdfgh")

    assert d["hay_fundamento"] is False
    assert d["sin_evidencia"] is not None
    assert "evidencia suficiente" in d["sin_evidencia"]
    assert d["pasajes"] == []


def test_una_norma_posterior_a_la_operacion_no_se_recupera() -> None:
    """§14: nunca se cita una norma que no regía ese día."""
    with _cliente(
        [_chunk(article="144", text="valor en aduana", valid_from=date(2025, 11, 19))],
        totales=1,
    ) as c:
        d = _preguntar(c, "valor en aduana", fecha="2024-03-15")

    assert d["pasajes"] == []
    assert d["hay_fundamento"] is False


def test_un_chunk_sintetico_no_fundamenta() -> None:
    """§8: un fixture completo sigue sin poder sostener nada jurídico."""
    with _cliente(
        [_chunk(article="1", text="valor en aduana", data_origin="SYNTHETIC")], totales=1
    ) as c:
        d = _preguntar(c, "valor en aduana")

    assert d["hay_fundamento"] is False


def test_una_pregunta_vacia_se_rechaza(cliente: TestClient) -> None:
    assert cliente.post("/copilot/consultas", json={"pregunta": "a"}).status_code == 422


def test_el_limite_tiene_tope(cliente: TestClient) -> None:
    """Más pasajes no responden mejor: diluyen."""
    from apps.api.routers.copilot import LIMITE_MAXIMO

    respuesta = cliente.post(
        "/copilot/consultas", json={"pregunta": "valor", "limite": LIMITE_MAXIMO + 1}
    )
    assert respuesta.status_code == 422


def test_la_cobertura_se_puede_consultar_sin_preguntar(cliente: TestClient) -> None:
    """La pantalla dice con qué va a buscar ANTES de la primera pregunta."""
    d = cliente.get("/copilot/cobertura").json()

    assert d["chunks_totales"] == 366
    assert d["busqueda_semantica_disponible"] is False
    assert d["pasajes"] == []


# ── El embedder conectado (Tarea 1 de Persona 1, 9 de septiembre) ────────────


class EmbedderFalso:
    """Se comporta como `EmbedderDegradable` sin llamar a nadie."""

    def __init__(self, *, funciona: bool = True) -> None:
        self._funciona = funciona
        self.uso_vectores = False
        self.motivo_degradacion: str | None = None

    def embed(self, textos: list[str]) -> list[list[float]]:
        if not self._funciona:
            self.motivo_degradacion = "ProviderResponseError: 429 Too Many Requests"
            return []
        self.uso_vectores = True
        return [[0.0] * 1536 for _ in textos]


def test_con_vectores_no_se_reordena_por_terminos() -> None:
    """EL FALLO QUE ENCONTRÉ VERIFICANDO CONTRA EL CORPUS REAL.

    Con vector, el almacén ya ordenó por distancia coseno y ese orden ES la
    pertinencia. Reordenar por solapamiento de palabras lo destruye: la
    consulta de Persona 1 —«mercancía que se deteriora si permanece almacenada
    mucho tiempo»— devolvía por coseno los artículos 34, 27 y 25, y mi
    reordenamiento los sustituía por el 119 y el 135-C, que sólo comparten las
    palabras «mercancía» y «permanece».
    """
    from apps.api.routers.copilot import Pasaje, _reordenar

    def _p(articulo: str, casados: int) -> Pasaje:
        return Pasaje(
            documento="Ley Aduanera",
            articulo=articulo,
            texto="x",
            cita=f"Ley Aduanera, artículo {articulo}",
            valid_from=date(2020, 1, 1),
            data_origin="OFFICIAL",
            puede_fundamentar=True,
            terminos_coincidentes=["t"] * casados,
        )

    # Orden del almacén por coseno: el 34 primero aunque case menos palabras.
    por_coseno = [_p("34", 1), _p("119", 3)]

    assert [x.articulo for x in _reordenar(por_coseno, uso_vectores=True)] == ["34", "119"]
    assert [x.articulo for x in _reordenar(por_coseno, uso_vectores=False)] == ["119", "34"]


def test_declara_semantica_solo_si_el_proveedor_respondio() -> None:
    with _cliente(
        [_chunk(article="34", text="conservación de mercancías")],
        embedder=EmbedderFalso(funciona=True),
        totales=366,
        vectorizados=366,
    ) as c:
        d = _preguntar(c, "mercancía que se deteriora almacenada")

    assert d["modo_busqueda"] == "SEMANTICA"
    assert d["busqueda_semantica_disponible"] is True
    assert d["degradado_por"] is None


def test_si_el_proveedor_falla_se_degrada_y_se_dice() -> None:
    """Un 429 no tumba la consulta: la hace peor, y eso se declara."""
    with _cliente(
        [_chunk(article="58", text="obligaciones del importador y el valor en aduana")],
        embedder=EmbedderFalso(funciona=False),
        totales=366,
        vectorizados=366,
    ) as c:
        d = _preguntar(c, "obligaciones del importador en el valor en aduana")

    assert d["modo_busqueda"] == "TERMINO_Y_VIGENCIA"
    assert d["busqueda_semantica_disponible"] is False
    assert d["degradado_por"] is not None
    assert "429" in d["degradado_por"]
    assert d["pasajes"], "la consulta siguió funcionando"


def test_sin_proveedor_la_consulta_sigue_funcionando() -> None:
    with _cliente(
        [_chunk(article="58", text="obligaciones del importador y el valor en aduana")],
        embedder=None,
        totales=366,
        vectorizados=366,
    ) as c:
        d = _preguntar(c, "obligaciones del importador en el valor en aduana")

    assert d["modo_busqueda"] == "TERMINO_Y_VIGENCIA"
    assert d["degradado_por"] == "no hay proveedor de embeddings configurado"
    assert d["pasajes"]
