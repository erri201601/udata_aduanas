"""Evidence Contract — el respaldo de toda decisión del sistema.

§45 del maestro dice que una tarea no está terminada porque el código corra, y
§49 cierra con las diez preguntas que ADUANERO OS debe poder responder sobre
cualquier decisión. Este módulo es lo que hace posible responderlas.

USO

    from core.evidence import builder, contract, questions

    norma = builder.legal_source(
        summary="La fracción 8471.30.01 comprende máquinas automáticas...",
        source_id=fuente_id,
        document_ref=DocumentRef(
            document="LIGIE 2022 (DOF)",
            article="Capítulo 84",
            url="https://www.snice.gob.mx/...",
            published_at=date(2022, 7, 7),
            content_hash="sha256:...",
        ),
        valid_from=date(2022, 7, 7),
        content_hash="sha256:...",
    )

    contract.assert_defensible(
        [norma], claim="clasificación 8471.30.01", operation_date=date(2024, 3, 15)
    )

    dossier = questions.answer_all(
        what="Fracción declarada distinta de la esperada",
        evidences=[norma],
        operation_date=date(2024, 3, 15),
    )

QUÉ GARANTIZA

- No se puede construir evidencia incompleta: falta un campo obligatorio y
  falla al construir, no al insertar.
- No se puede sostener una afirmación jurídica sin una fuente recuperada.
- No se puede citar una norma que no regía en la fecha de la operación.
- Un caso de CBP CROSS o EBTI no puede pasar por fundamento mexicano.

QUÉ NO GARANTIZA

Que la evidencia sea correcta. Garantiza que sea completa, atribuible y
temporalmente aplicable. Juzgar si una norma dice lo que creemos que dice
sigue siendo trabajo humano, y por eso existe `requires_human_review`.

PENDIENTE CON PERSONA 2

`intelligence.evidence_records` no tiene columna `evidence_kind`, así que hoy
el tipo sólo se proyecta sobre `created_by`, que admite 16 caracteres y no
distingue LEGAL_SOURCE de COMPARABLE. Es justo la distinción que impide que un
precedente extranjero se lea como fundamento mexicano.

`to_record_fields()` ya emite `evidence_kind` para que el día que exista la
columna el ensamblado no cambie. Requiere migración y aprobación: es un cambio
al Canonical Model (§10.9).
"""

from __future__ import annotations

from core.evidence import builder, contract, questions
from core.evidence.errors import (
    EvidenceError,
    EvidenceOutOfValidityError,
    IncompleteEvidenceError,
    NotLegalBasisError,
    UnsupportedClaimError,
)
from core.evidence.kinds import LEGAL_BASIS_KINDS, REQUIRED_FIELDS, EvidenceKind
from core.evidence.questions import UNKNOWN, Dossier
from core.evidence.types import DocumentRef, Evidence

__all__ = [
    "LEGAL_BASIS_KINDS",
    "REQUIRED_FIELDS",
    "UNKNOWN",
    "DocumentRef",
    "Dossier",
    "Evidence",
    "EvidenceError",
    "EvidenceKind",
    "EvidenceOutOfValidityError",
    "IncompleteEvidenceError",
    "NotLegalBasisError",
    "UnsupportedClaimError",
    "builder",
    "contract",
    "questions",
]
