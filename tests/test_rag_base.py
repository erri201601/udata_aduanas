"""Tests del RAG jurídico.

Dos tests mandan sobre el resto:

`test_un_fixture_no_puede_fundamentar` — un chunk SYNTHETIC no puede sostener
una afirmación jurídica por muy completo que esté. El Evidence Contract exige
source_id, document_ref, valid_from y content_hash, y ninguno mira la
procedencia: sin este filtro, un fixture con un source_id inventado contaría
como norma y el sistema produciría clasificaciones "defendibles" fundadas en
ley inventada.

`test_no_recupera_una_norma_posterior_a_la_operacion` — la regla 5 del
CLAUDE.md. Citar un texto que ese día no existía es indefendible.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from rag import (
    ORIGENES_QUE_FUNDAMENTAN,
    LegalChunk,
    MemoriaChunkStore,
    hash_contenido,
    recuperar,
    trocear,
)

pytestmark = pytest.mark.unit

FRAGMENTO = Path("tests/fixtures/ley_aduanera_fragmento.txt")
OPERACION = date(2024, 3, 15)


def _chunks(origen: str = "SYNTHETIC") -> list[LegalChunk]:
    return trocear(
        FRAGMENTO.read_text(encoding="utf-8"),
        document="Ley Aduanera",
        data_origin=origen,  # type: ignore[arg-type]
        valid_from=date(1995, 12, 15),
    )


def _store(origen: str = "OFFICIAL") -> MemoriaChunkStore:
    s = MemoriaChunkStore()
    s.add(_chunks(origen))
    return s


# ── Procedencia: un fixture no es fundamento ────────────────────────────────


def test_un_fixture_no_puede_fundamentar() -> None:
    """EL TEST QUE IMPORTA.

    Sin esto, el sistema produciría clasificaciones «defendibles» fundadas en
    ley inventada — el peor fallo que puede tener.
    """
    for chunk in _chunks("SYNTHETIC"):
        assert not chunk.puede_fundamentar


def test_synthetic_no_esta_entre_los_origenes_que_fundamentan() -> None:
    assert "SYNTHETIC" not in ORIGENES_QUE_FUNDAMENTAN
    assert "OFFICIAL" in ORIGENES_QUE_FUNDAMENTAN


def test_los_fixtures_no_llegan_a_la_recuperacion() -> None:
    """El camino cómodo es el seguro: hay que pedir lo inseguro a mano."""
    r = recuperar("documento electrónico", on_date=OPERACION, store=_store("SYNTHETIC"))

    assert r.chunks == ()
    assert not r.hay_fundamento
    assert r.descartados_por_origen > 0 or r.descartados_por_vigencia >= 0


def test_se_pueden_inspeccionar_a_sabiendas() -> None:
    """Para desarrollo, con el flag explícito."""
    r = recuperar(
        "documento electrónico",
        on_date=OPERACION,
        store=_store("SYNTHETIC"),
        permitir_no_fundamentables=True,
    )

    assert r.chunks
    assert not r.hay_fundamento  # siguen sin fundamentar


def test_sin_fundamento_hay_un_mensaje_no_una_cita_inventada() -> None:
    r = recuperar("qué dice el artículo 999", on_date=OPERACION, store=MemoriaChunkStore())

    assert not r.hay_fundamento
    assert r.citas == ()
    assert "No tengo evidencia suficiente" in r.sin_evidencia()


# ── Vigencia: por chunk, no por documento ───────────────────────────────────


def test_la_vigencia_es_por_chunk_no_por_documento() -> None:
    """El 36-A se reformó en 2018; el 35 viene de 1995.

    Con vigencia por documento, preguntar qué regía en 2016 devolvería el
    texto de 2018 y se citaría un artículo que ese día no existía.
    """
    por_articulo = {c.article: c for c in _chunks()}

    assert por_articulo["36-A"].valid_from == date(2018, 6, 25)
    assert por_articulo["35"].valid_from == date(1995, 12, 15)


def test_no_recupera_una_norma_posterior_a_la_operacion() -> None:
    """Regla 5 del CLAUDE.md: nunca regulación posterior a la operación.

    El 36-A rige desde 2018; en una operación de 2016 no puede aparecer.
    """
    r = recuperar("documento electrónico", on_date=date(2016, 5, 1), store=_store())

    assert "36-A" not in {c.article for c in r.chunks}
    assert "36" in {c.article for c in r.chunks}


def test_el_filtro_temporal_atrapa_a_un_almacen_descuidado() -> None:
    """La regla se aplica DOS veces, y ésta es la segunda.

    Si mañana alguien escribe un `ChunkStore` sobre pgvector y olvida el
    filtro en el SQL, la capa de recuperación lo sigue cumpliendo. El
    contador dice cuántos tuvo que descartar, que es cómo se detecta ese
    almacén descuidado en vez de que pase inadvertido.
    """

    class AlmacenSinFiltro:
        """Devuelve todo, como haría un SQL al que le falta el WHERE."""

        def __init__(self, chunks: list[LegalChunk]) -> None:
            self._chunks = chunks

        def add(self, chunks: list[LegalChunk]) -> int:  # pragma: no cover
            self._chunks.extend(chunks)
            return len(chunks)

        def search(self, **_kwargs: object) -> list[LegalChunk]:
            return self._chunks

    r = recuperar(
        "documento electrónico",
        on_date=date(2016, 5, 1),
        store=AlmacenSinFiltro(_chunks("OFFICIAL")),  # type: ignore[arg-type]
    )

    assert "36-A" not in {c.article for c in r.chunks}
    assert r.descartados_por_vigencia > 0


def test_si_recupera_lo_que_regia_ese_dia() -> None:
    r = recuperar("documento electrónico", on_date=OPERACION, store=_store())

    assert "36-A" in {c.article for c in r.chunks}
    assert r.hay_fundamento


def test_valid_to_nulo_significa_vigente() -> None:
    chunk = _chunks()[0]

    assert chunk.valid_to is None
    assert chunk.vigente_en(date(2030, 1, 1))


# ── Troceado: la estructura real del DOF ────────────────────────────────────


def test_reconoce_el_sufijo_con_letra() -> None:
    """36-A y 36 son artículos distintos. Confundirlos cambia la obligación."""
    articulos = {c.article for c in _chunks()}

    assert "36" in articulos
    assert "36-A" in articulos


def test_las_fracciones_son_chunks_propios() -> None:
    """Se citan solas: «artículo 36-A fracción I»."""
    fracciones = [c for c in _chunks() if "fracción" in c.article]

    assert len(fracciones) == 3
    assert "36-A fracción I" in {c.article for c in fracciones}


def test_reconoce_los_transitorios() -> None:
    """Fijan cuándo entra en vigor lo demás: perderlos es perder la vigencia."""
    transitorios = [c for c in _chunks() if c.article.startswith("Transitorio")]

    assert len(transitorios) == 2


def test_conserva_la_jerarquia_para_poder_citar() -> None:
    chunk = next(c for c in _chunks() if c.article == "36-A")

    assert chunk.path is not None
    assert "TÍTULO TERCERO" in chunk.path


def test_el_hash_ignora_el_formato_pero_no_el_texto() -> None:
    """El mismo artículo de dos PDFs difiere en saltos de línea, no en fondo."""
    assert hash_contenido("Artículo  35.\n\n  Se entiende") == hash_contenido(
        "Artículo 35. Se entiende"
    )
    assert hash_contenido("uno") != hash_contenido("dos")


def test_la_cita_se_puede_leer_en_un_dictamen() -> None:
    chunk = next(c for c in _chunks() if c.article == "36-A fracción I")

    assert chunk.cita() == "Ley Aduanera, artículo 36-A fracción I"


# ── Contrato con quien cargue las normas ────────────────────────────────────


def test_todo_chunk_declara_lo_que_el_contrato_de_evidencia_exigira() -> None:
    """Es lo que Persona 2 tiene que poder llenar al cargar la Ley Aduanera."""
    for chunk in _chunks():
        assert chunk.document
        assert chunk.article
        assert chunk.text
        assert chunk.valid_from
        assert chunk.content_hash.startswith("sha256:")
        assert chunk.data_origin


def test_data_origin_es_obligatorio() -> None:
    """Un chunk sin procedencia declarada no se puede indexar."""
    with pytest.raises(ValueError, match="data_origin"):
        LegalChunk(
            document="x",
            article="1",
            text="y",
            valid_from=date(2020, 1, 1),
            content_hash=hash_contenido("y"),
        )  # type: ignore[call-arg]
