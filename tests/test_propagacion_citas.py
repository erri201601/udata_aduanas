"""La cadena que enciende el Sentinel: LegalChunk → LegalRef → decisión.

POR QUÉ EXISTE ESTA CADENA

El Sentinel pregunta «¿qué decisiones se apoyaron en una norma que no estaba
vigente en su fecha de operación?». Une por
`classification_decisions.legal_rule_ids`, que guarda ids de `legal_rules`.
Pero el RAG cita CHUNKS, y hasta el PR #70 de Persona 2 no había ninguna
columna que ligara un chunk con su norma: la consulta estaba bien escrita y no
podía dar señal nunca.

Estos tests fijan los cuatro eslabones. Si alguno se rompe, la columna vuelve
a llegar vacía y el Sentinel vuelve a decir `trazable: false` — en silencio,
que es lo peor: la consulta seguiría ejecutándose sin error.

Persona 1 aprobó este cambio de contrato el 9 de septiembre.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from core.evidence import builder
from core.evidence.kinds import EvidenceKind
from rag.evidencia import a_legal_ref, a_legal_refs
from rag.retrieval import Recuperacion
from rag.types import LegalChunk

pytestmark = pytest.mark.unit

REGLA = uuid.uuid4()


def _chunk(*, legal_rule_id: uuid.UUID | None = REGLA, data_origin: str = "OFFICIAL") -> LegalChunk:
    return LegalChunk(
        source_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        legal_rule_id=legal_rule_id,
        document="Ley Aduanera",
        article="64",
        text="El valor en aduana de las mercancías será el valor de transacción.",
        content_hash="sha256:x",
        data_origin=data_origin,  # type: ignore[arg-type]
        valid_from=date(2020, 1, 1),
        url="https://dof.gob.mx/x",
    )


# ── Eslabón 1: el chunk lo lleva ─────────────────────────────────────────────


def test_un_chunk_puede_llevar_el_id_de_su_norma() -> None:
    assert _chunk().legal_rule_id == REGLA


def test_un_chunk_sin_norma_detras_no_es_un_error() -> None:
    """Corpus cargado antes de la columna, o fixtures. Es una cita que no se
    puede auditar, y se sabe — no una excepción."""
    assert _chunk(legal_rule_id=None).legal_rule_id is None


# ── Eslabón 2: LegalRef lo propaga ───────────────────────────────────────────


def test_la_referencia_conserva_el_id_de_la_norma() -> None:
    """EL ESLABÓN QUE FALTABA.

    `DocumentRef` identifica la norma como se CITA y eso basta para un
    dictamen. No basta para cruzarla con `legal_rule_ids`: casar por la cadena
    «Ley Aduanera, artículo 64» sería frágil justo donde hace falta ser
    exacto.
    """
    ref = a_legal_ref(_chunk())

    assert ref.legal_rule_id == REGLA
    assert ref.document_ref.article == "64"


def test_sin_norma_detras_la_referencia_lo_dice_con_none() -> None:
    assert a_legal_ref(_chunk(legal_rule_id=None)).legal_rule_id is None


def test_un_chunk_sintetico_sigue_sin_poder_fundamentar() -> None:
    """Llevar `legal_rule_id` no cambia el §8.1: la procedencia manda."""
    from core.evidence.errors import SyntheticLegalBasisError

    with pytest.raises(SyntheticLegalBasisError):
        a_legal_ref(_chunk(data_origin="SYNTHETIC"))


# ── Eslabón 3: la evidencia lo recoge ────────────────────────────────────────


def test_la_evidencia_legal_lleva_el_id_de_la_norma() -> None:
    ref = a_legal_ref(_chunk())
    evidencia = builder.legal_source(
        summary="sustenta",
        source_id=uuid.uuid4(),
        document_ref=ref.document_ref,
        valid_from=ref.valid_from,
        content_hash=ref.content_hash,
        data_origin=ref.data_origin,
        legal_rule_ids=(ref.legal_rule_id,) if ref.legal_rule_id else (),
    )

    assert evidencia.legal_rule_ids == (REGLA,)


# ── Eslabón 4: la decisión lo persiste ───────────────────────────────────────


class _Outcome:
    """Sólo lo que `_normas_citadas` mira."""

    def __init__(self, *evidencias: object) -> None:
        self.evidences = list(evidencias)


def _evidencia(kind: EvidenceKind, *ids: uuid.UUID) -> object:
    return type("E", (), {"kind": kind, "legal_rule_ids": ids})()


def test_se_guardan_las_normas_de_la_evidencia_legal() -> None:
    from database.repositories.classification import _normas_citadas

    otra = uuid.uuid4()
    outcome = _Outcome(_evidencia(EvidenceKind.LEGAL_SOURCE, REGLA, otra))

    assert _normas_citadas(outcome) == [REGLA, otra]  # type: ignore[arg-type]


def test_solo_cuenta_la_evidencia_que_puede_fundamentar() -> None:
    """Una evidencia DETERMINISTIC no aporta norma: no es fundamento jurídico."""
    from database.repositories.classification import _normas_citadas

    outcome = _Outcome(
        _evidencia(EvidenceKind.DETERMINISTIC, uuid.uuid4()),
        _evidencia(EvidenceKind.LEGAL_SOURCE, REGLA),
    )

    assert _normas_citadas(outcome) == [REGLA]  # type: ignore[arg-type]


def test_no_se_repiten_las_normas_ni_se_reordenan() -> None:
    """El orden es el de la cita del motor; reordenar no ganaría nada."""
    from database.repositories.classification import _normas_citadas

    a, b = uuid.uuid4(), uuid.uuid4()
    outcome = _Outcome(
        _evidencia(EvidenceKind.LEGAL_SOURCE, a, b),
        _evidencia(EvidenceKind.LEGAL_SOURCE, a),
    )

    assert _normas_citadas(outcome) == [a, b]  # type: ignore[arg-type]


def test_sin_evidencia_legal_la_columna_queda_vacia() -> None:
    """Vacía es la verdad: no hubo norma que citar."""
    from database.repositories.classification import _normas_citadas

    assert _normas_citadas(_Outcome()) == []  # type: ignore[arg-type]


# ── La cadena entera ─────────────────────────────────────────────────────────


def test_de_la_recuperacion_a_las_referencias_sin_perder_el_id() -> None:
    recuperacion = Recuperacion(chunks=(_chunk(),), on_date=date(2024, 3, 15))

    refs = a_legal_refs(recuperacion)

    assert len(refs) == 1
    assert refs[0].legal_rule_id == REGLA
