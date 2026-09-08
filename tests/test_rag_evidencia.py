"""Tests del puente entre el RAG y el contrato de evidencia.

Es el cable que hace defendible una clasificación, y por eso el test que
manda es que un chunk SYNTHETIC no lo cruce: si lo hiciera, el sistema
produciría clasificaciones "defendibles" fundadas en ley inventada.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from core.evidence.errors import SyntheticLegalBasisError
from core.evidence.types import LegalRef
from rag import (
    LegalChunk,
    MemoriaChunkStore,
    a_legal_ref,
    a_legal_refs,
    citar,
    hash_contenido,
    recuperar,
    trocear,
)

pytestmark = pytest.mark.unit

FRAGMENTO = Path("tests/fixtures/ley_aduanera_fragmento.txt")
OPERACION = date(2024, 3, 15)


def _chunks(origen: str) -> list[LegalChunk]:
    return trocear(
        FRAGMENTO.read_text(encoding="utf-8"),
        document="Ley Aduanera",
        data_origin=origen,  # type: ignore[arg-type]
        valid_from=date(1995, 12, 15),
    )


def _recuperacion(origen: str):
    store = MemoriaChunkStore()
    store.add(_chunks(origen))
    return recuperar("documento electrónico", on_date=OPERACION, store=store)


# ── La salvaguarda ──────────────────────────────────────────────────────────


def test_un_chunk_sintetico_no_cruza_el_puente() -> None:
    """EL TEST QUE IMPORTA.

    Si lo cruzara, el sistema produciría clasificaciones «defendibles»
    fundadas en ley inventada.
    """
    sintetico = _chunks("SYNTHETIC")[0]

    with pytest.raises(SyntheticLegalBasisError, match="no puede sostener"):
        a_legal_ref(sintetico)


def test_lanza_en_vez_de_devolver_none() -> None:
    """Un `None` acabaría filtrado en una comprensión y nadie sabría por qué.

    La excepción dice qué norma se descartó y con qué origen.
    """
    sintetico = _chunks("SYNTHETIC")[0]

    with pytest.raises(SyntheticLegalBasisError) as exc:
        a_legal_ref(sintetico)

    assert "SYNTHETIC" in str(exc.value)
    assert "Ley Aduanera" in str(exc.value)


def test_un_corpus_de_fixtures_no_produce_ninguna_referencia() -> None:
    """Las dos capas juntas: recuperar descarta, y el puente no convierte."""
    assert a_legal_refs(_recuperacion("SYNTHETIC")) == ()


def test_un_corpus_oficial_si_produce_referencias() -> None:
    refs = a_legal_refs(_recuperacion("OFFICIAL"))

    assert refs
    assert all(isinstance(r, LegalRef) for r in refs)


# ── Lo que viaja en la referencia ───────────────────────────────────────────


def test_la_referencia_conserva_la_vigencia_del_chunk() -> None:
    """El 36-A rige desde 2018, no desde la publicación del documento."""
    chunk = next(c for c in _chunks("OFFICIAL") if c.article == "36-A")
    ref = a_legal_ref(chunk)

    assert ref.valid_from == date(2018, 6, 25)
    assert ref.valid_to is None


def test_la_referencia_conserva_el_hash_verificable() -> None:
    """Es lo que hace la cita comprobable contra el documento."""
    chunk = _chunks("OFFICIAL")[0]
    ref = a_legal_ref(chunk)

    assert ref.content_hash == chunk.content_hash
    assert ref.content_hash.startswith("sha256:")
    assert ref.document_ref.content_hash == chunk.content_hash


def test_la_referencia_conserva_el_origen() -> None:
    """Sin él, el contrato no podría rechazar lo que no fundamenta."""
    assert a_legal_ref(_chunks("OFFICIAL")[0]).data_origin == "OFFICIAL"


def test_la_referencia_identifica_el_articulo_no_el_documento() -> None:
    """Citar «Ley Aduanera» entera no sirve en un dictamen."""
    chunk = next(c for c in _chunks("OFFICIAL") if c.article == "36-A fracción I")
    ref = a_legal_ref(chunk)

    assert ref.document_ref.article == "36-A fracción I"
    assert ref.document_ref.document == "Ley Aduanera"


def test_las_citas_se_leen_como_en_un_dictamen() -> None:
    citas = citar(a_legal_refs(_recuperacion("OFFICIAL")))

    assert citas
    assert all(c.startswith("Ley Aduanera, artículo ") for c in citas)


# ── Integración con el contrato de Persona 1 ────────────────────────────────


def test_la_referencia_construye_una_evidencia_legal() -> None:
    """El puente produce exactamente lo que el contrato acepta."""
    from core.evidence import builder

    ref = a_legal_ref(next(c for c in _chunks("OFFICIAL") if c.article == "36-A"))
    evidencia = builder.legal_source(
        summary="El importador debe transmitir el documento electrónico.",
        source_id=__import__("uuid").uuid4(),
        document_ref=ref.document_ref,
        valid_from=ref.valid_from,
        content_hash=ref.content_hash,
        data_origin=ref.data_origin,
    )

    assert evidencia.is_legal_basis


def test_una_norma_sintetica_no_es_fundamento_aunque_se_construya() -> None:
    """La tercera capa. Si el puente fallara, el contrato sigue parando.

    Construir la evidencia sí se permite —es un objeto válido— pero
    `is_legal_basis` da `False`: tiene todos los campos que exige
    `LEGAL_SOURCE` y aun así no es ley.
    """
    import uuid

    from core.evidence import builder
    from core.evidence.types import DocumentRef

    inventada = builder.legal_source(
        summary="Norma inventada.",
        source_id=uuid.uuid4(),
        document_ref=DocumentRef(document="Ley Falsa", article="1"),
        valid_from=date(2020, 1, 1),
        content_hash=hash_contenido("x"),
        data_origin="SYNTHETIC",
    )

    assert not inventada.is_legal_basis


def test_el_contrato_rechaza_una_clasificacion_fundada_en_lo_sintetico() -> None:
    """Donde de verdad se para: al exigir que la decisión sea defendible."""
    import uuid

    from core.evidence import builder, contract
    from core.evidence.types import DocumentRef

    inventada = builder.legal_source(
        summary="Norma inventada.",
        source_id=uuid.uuid4(),
        document_ref=DocumentRef(document="Ley Falsa", article="1"),
        valid_from=date(2020, 1, 1),
        content_hash=hash_contenido("x"),
        data_origin="SYNTHETIC",
    )

    with pytest.raises(SyntheticLegalBasisError):
        contract.assert_defensible([inventada], claim="fracción 84713001", operation_date=OPERACION)
