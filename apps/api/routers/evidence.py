"""Dossier de evidencia: las diez preguntas del §49 sobre una decisión.

Es la pantalla que se enseña cuando alguien audita una clasificación, y por
eso es donde mentir cuesta más caro. Un dossier incompleto pintado como
completo miente.

`Dossier.unanswered` dice qué preguntas la evidencia disponible no alcanza a
responder, y esta API lo devuelve tal cual. Se va a ver peor que si se
rellenaran los huecos. Eso es correcto.

EL DOSSIER SE ENSAMBLA, NO SE GUARDA

`answer_all()` lo construye a partir de las evidencias persistidas. Eso no es
lo mismo que reejecutar el motor: las evidencias son hechos ya escritos, y
ensamblar una vista sobre ellas no puede cambiar lo que se decidió aquel día.

EVIDENCIAS QUE NO SE PUEDEN INTERPRETAR

`Evidence` exige `kind`, y hay filas con `evidence_kind` en NULL. Esas no se
convierten y NO se cuelan en el dossier: se cuentan aparte en
`uninterpretable_evidences`. Meterlas suponiéndoles un tipo sería inventar la
procedencia de un dato — el mismo error que la pantalla de Classification
existe para evitar.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
import structlog
from core.evidence import questions
from core.evidence.kinds import EvidenceKind
from core.evidence.types import DocumentRef, Evidence
from database.models import ClassificationDecision, EvidenceRecord
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from apps.api.db import SessionDep

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

log = structlog.stdlib.get_logger("apps.api.evidencia")

router = APIRouter(prefix="/evidence", tags=["evidence"])

#: Las diez preguntas del §49, en el orden en que se responden. El orden no es
#: cosmético: quien audita sigue esta secuencia — qué, por qué, con qué regla,
#: con qué fuente, de qué versión, vigente cuándo, con qué dato, con cuánta
#: confianza, cuánto dinero, y si hace falta una persona.
PREGUNTAS: tuple[tuple[str, str], ...] = (
    ("what", "¿Qué detectaste?"),
    ("why", "¿Por qué?"),
    ("which_rule", "¿Con qué regla?"),
    ("which_source", "¿Con qué fuente?"),
    ("source_version", "¿Qué versión de esa fuente?"),
    ("validity", "¿Cuándo era vigente?"),
    ("data_used", "¿Qué dato utilizaste?"),
    ("confidence", "¿Cuánta confianza tienes?"),
    ("money_impact", "¿Cuánto dinero representa?"),
    ("requires_human_review", "¿Requiere revisión humana?"),
)


class DossierRead(BaseModel):
    """Las diez respuestas, más lo que no se pudo responder."""

    decision_id: uuid.UUID
    what: str
    why: str
    which_rule: str
    which_source: list[str] = Field(default_factory=list)
    source_version: list[str] = Field(default_factory=list)
    validity: list[str] = Field(default_factory=list)
    data_used: dict[str, Any] = Field(default_factory=dict)
    confidence: str | None = None
    money_impact: str
    requires_human_review: bool

    unanswered: list[str] = Field(default_factory=list)
    """Las que la evidencia no alcanza a contestar. Se muestran."""

    is_complete: bool = False
    """¿Están las diez? Es la diferencia entre «documentado» y «tiene huecos»."""

    uninterpretable_evidences: int = 0
    """Filas de evidencia sin `evidence_kind`, que no se pudieron usar.

    No se descartan en silencio: si el dossier tiene huecos y hay evidencias
    inservibles, quien audita necesita saber que la causa puede ser esa.
    """


def _a_referencia(refs: Sequence[Mapping[str, Any]] | None) -> DocumentRef | None:
    """La primera referencia documental de la fila, si la trae.

    `to_row()` emite una lista porque el modelo la admite, pero `Evidence`
    tiene un solo `document_ref`: se toma la primera y las demás no se
    inventan. Una referencia mal formada NO tumba el dossier —se devuelve
    `None` y la pregunta queda sin responder, que es la respuesta honesta.
    """
    if not refs:
        return None
    try:
        return DocumentRef.model_validate(dict(refs[0]))
    except ValidationError:
        log.warning("evidencia.referencia_ilegible", ref=refs[0])
        return None


def _a_evidence(fila: EvidenceRecord) -> Evidence | None:
    """Convierte una fila en `Evidence`, o `None` si no declara su tipo.

    No se le supone un tipo. Una evidencia cuya procedencia no consta no puede
    entrar al dossier como si constara.
    """
    if not fila.evidence_kind:
        return None

    return Evidence(
        kind=EvidenceKind(fila.evidence_kind),
        summary=fila.summary or "",
        source_id=fila.source_id,
        # `Evidence.to_row()` guarda la referencia en `document_refs`; leerla de
        # vuelta es lo que faltaba. Sin esto `document_ref` era siempre `None`,
        # y la pregunta del §49 —«¿con qué fuente?»— salía sin responder aunque
        # la fila tuviera documento, artículo, URL y hash.
        document_ref=_a_referencia(fila.document_refs),
        # Sin el origen, `is_legal_basis` no puede distinguir una norma real de
        # una sintética. Se lee aquí, no se supone: un defecto razonable
        # convertiría en oficial todo lo que alguien olvidara marcar.
        data_origin=fila.data_origin,
        content_hash=fila.content_hashes[0] if fila.content_hashes else None,
        legal_rule_ids=tuple(fila.legal_rule_ids or ()),
        model_provider=fila.model_provider,
        model_name=fila.model_name,
        prompt_version=fila.prompt_version,
        engine_version=fila.engine_version,
        # La pareja de cada versión. Sin ellos, `which_rule` sólo podía hablar
        # de versiones: «None (motor 0.1.0)» para el motor y «None v0.1» para
        # el extractor. Es el mismo hueco que tuvieron `document_ref`,
        # `data_origin` y la vigencia, y por la misma razón: el campo se
        # escribía en el dominio y no había columna que leer.
        rule_id=fila.rule_id,
        prompt_id=fila.prompt_id,
        # Sin esto, `covers()` trataba TODA evidencia como si no fuera
        # temporal (nunca restringía fecha) y la pregunta del §49 —«¿cuándo
        # era vigente?»— salía siempre "UNKNOWN → vigente", aunque la norma
        # citada sí tuviera vigencia conocida al momento de clasificar. El
        # hueco no era la lógica de `covers()`/`questions.py` —ya trataban
        # `None` como UNKNOWN, correctamente—: era que la columna nunca
        # existía para que hubiera algo que leer.
        valid_from=fila.valid_from,
        valid_to=fila.valid_to,
    )


@router.get("/{decision_id}", summary="Dossier §49 de una decisión")
def obtener_dossier(decision_id: uuid.UUID, session: SessionDep) -> DossierRead:
    decision = session.get(ClassificationDecision, decision_id)
    if decision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisión no encontrada")

    filas = session.scalars(
        sa.select(EvidenceRecord).where(
            sa.or_(
                EvidenceRecord.id == decision.evidence_id,
                sa.and_(
                    EvidenceRecord.subject_kind == "classification_decision",
                    EvidenceRecord.subject_id == decision_id,
                ),
            )
        )
    ).all()

    convertidas = [_a_evidence(f) for f in filas]
    evidencias = [e for e in convertidas if e is not None]
    sin_tipo = len(convertidas) - len(evidencias)

    dossier = questions.answer_all(
        what=decision.reasoning or f"Clasificación {decision.fraction_code or 'sin resolver'}",
        evidences=evidencias,
        operation_date=decision.operation_date,
        confidence=decision.confidence,
        money_impact=(
            f"{decision.estimated_impact_amount} "
            f"{decision.estimated_impact_amount_currency or ''}".strip()
            if decision.estimated_impact_amount is not None
            else None
        ),
        requires_human_review=decision.requires_human_review,
        data_used=decision.input_snapshot or {},
    )

    return DossierRead(
        decision_id=decision_id,
        what=dossier.what,
        why=dossier.why,
        which_rule=dossier.which_rule,
        which_source=list(dossier.which_source),
        source_version=list(dossier.source_version),
        validity=list(dossier.validity),
        data_used=dossier.data_used,
        confidence=str(dossier.confidence) if dossier.confidence is not None else None,
        money_impact=dossier.money_impact,
        requires_human_review=dossier.requires_human_review,
        unanswered=list(dossier.unanswered),
        is_complete=dossier.is_complete,
        uninterpretable_evidences=sin_tipo,
    )
