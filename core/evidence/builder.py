"""Constructores de evidencia.

Cada tipo tiene su propia función y todas validan antes de devolver nada. La
razón de que no exista un constructor genérico es deliberada: un
`Evidence(kind=..., **lo_que_sea)` permitiría crear una fuente jurídica sin
`content_hash` o una salida de modelo sin `prompt_version`, y ese registro
llegaría a la base con apariencia de evidencia válida.

El error se lanza al construir, donde está el defecto, no al insertar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.evidence.errors import IncompleteEvidenceError
from core.evidence.kinds import DATA_ORIGINS, REQUIRED_FIELDS, EvidenceKind
from core.evidence.types import DocumentRef, Evidence

if TYPE_CHECKING:
    import uuid
    from datetime import date, datetime
    from decimal import Decimal


def _exigir(kind: EvidenceKind, presentes: dict[str, Any]) -> None:
    """Comprueba que estén todos los campos obligatorios del tipo.

    Una cadena vacía cuenta como ausente: `prompt_version=""` no documenta
    nada y pasaría un chequeo de `is None`.
    """
    faltantes = {
        campo
        for campo in REQUIRED_FIELDS[kind]
        if presentes.get(campo) is None
        or (isinstance(presentes.get(campo), str) and not presentes[campo].strip())
    }
    if faltantes:
        raise IncompleteEvidenceError(kind, faltantes)


def legal_source(
    *,
    summary: str,
    source_id: uuid.UUID,
    document_ref: DocumentRef,
    valid_from: date,
    content_hash: str,
    data_origin: str,
    valid_to: date | None = None,
    legal_rule_ids: tuple[uuid.UUID, ...] = (),
    excerpt: str | None = None,
) -> Evidence:
    """Evidencia de una norma recuperada. El único fundamento jurídico.

    `valid_to = None` significa vigente. Nunca se rellena con una fecha
    supuesta: si no consta el fin de vigencia, no consta (§14).

    `content_hash` es obligatorio porque es lo que hace la cita verificable.
    Una URL de gobierno puede cambiar de contenido sin cambiar de dirección.

    `data_origin` es obligatorio y no tiene valor por omisión a propósito. Un
    defecto razonable —`"OFFICIAL"`, digamos— convertiría en oficial todo lo
    que alguien olvidara marcar, que es exactamente al revés de como debe
    fallar esto. Quien construye la evidencia sabe de dónde sacó el texto;
    tiene que decirlo.

    Se construye igual con `SYNTHETIC`: poder representar una norma sintética
    es necesario para las pruebas y las demos. Lo que no puede es fundamentar,
    y de eso se encarga `assert_legal_basis`.
    """
    _exigir(
        EvidenceKind.LEGAL_SOURCE,
        {
            "source_id": source_id,
            "document_ref": document_ref,
            "valid_from": valid_from,
            "content_hash": content_hash,
            "data_origin": data_origin,
        },
    )
    if data_origin not in DATA_ORIGINS:
        raise ValueError(
            f"data_origin '{data_origin}' no es uno de los cinco valores "
            f"cerrados: {', '.join(sorted(DATA_ORIGINS))} (regla 3 de CLAUDE.md)."
        )
    return Evidence(
        kind=EvidenceKind.LEGAL_SOURCE,
        summary=summary,
        source_id=source_id,
        document_ref=document_ref,
        valid_from=valid_from,
        valid_to=valid_to,
        content_hash=content_hash,
        data_origin=data_origin,
        legal_rule_ids=legal_rule_ids,
        excerpt=excerpt,
    )


def model_output(
    *,
    summary: str,
    model_provider: str,
    model_name: str,
    prompt_id: str,
    prompt_version: str,
    confidence: Decimal | None = None,
    excerpt: str | None = None,
    source_id: uuid.UUID | None = None,
) -> Evidence:
    """Evidencia de que un modelo produjo un dato.

    Los cuatro campos obligatorios son los que permiten reproducir la salida.
    Sin `prompt_version` no se puede saber con qué instrucciones se generó, y
    una salida irreproducible no es auditable.

    NO es fundamento jurídico: para eso acompáñala de un `legal_source`.
    """
    _exigir(
        EvidenceKind.MODEL_OUTPUT,
        {
            "model_provider": model_provider,
            "model_name": model_name,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
        },
    )
    return Evidence(
        kind=EvidenceKind.MODEL_OUTPUT,
        summary=summary,
        model_provider=model_provider,
        model_name=model_name,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        confidence=confidence,
        excerpt=excerpt,
        source_id=source_id,
    )


def deterministic(
    *,
    summary: str,
    rule_id: str,
    engine_version: str,
    inputs: dict[str, Any] | None = None,
) -> Evidence:
    """Evidencia de una regla de código, sin modelo de por medio.

    `inputs` guarda con qué datos se ejecutó la regla: es lo que permite
    reproducir el resultado exacto, que es la ventaja de lo determinista sobre
    lo interpretado.
    """
    _exigir(
        EvidenceKind.DETERMINISTIC,
        {"rule_id": rule_id, "engine_version": engine_version},
    )
    return Evidence(
        kind=EvidenceKind.DETERMINISTIC,
        summary=summary,
        rule_id=rule_id,
        engine_version=engine_version,
        inputs=inputs or {},
    )


def human(
    *,
    summary: str,
    reviewer: str,
    reviewed_at: datetime,
    confidence: Decimal | None = None,
    excerpt: str | None = None,
) -> Evidence:
    """Evidencia de que una persona revisó y validó.

    `reviewer` es obligatorio: una validación anónima no se puede repreguntar,
    y estas correcciones son las que alimentan la evaluación de §39.
    """
    _exigir(EvidenceKind.HUMAN, {"reviewer": reviewer, "reviewed_at": reviewed_at})
    return Evidence(
        kind=EvidenceKind.HUMAN,
        summary=summary,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        confidence=confidence,
        excerpt=excerpt,
    )


def comparable(
    *,
    summary: str,
    jurisdiction: str,
    case_ref: str,
    document_ref: DocumentRef,
    excerpt: str | None = None,
) -> Evidence:
    """Evidencia de un caso internacional comparable: CBP CROSS, EBTI, WCO.

    `jurisdiction` es obligatoria precisamente porque es lo que impide
    confundirlo con fundamento mexicano. Quien lea la decisión tiene que ver
    que esto viene de otro sistema legal.

    Apoyo interpretativo únicamente. `assert_legal_basis` la rechaza.
    """
    _exigir(
        EvidenceKind.COMPARABLE,
        {
            "jurisdiction": jurisdiction,
            "case_ref": case_ref,
            "document_ref": document_ref,
        },
    )
    return Evidence(
        kind=EvidenceKind.COMPARABLE,
        summary=summary,
        jurisdiction=jurisdiction,
        case_ref=case_ref,
        document_ref=document_ref,
        excerpt=excerpt,
    )
