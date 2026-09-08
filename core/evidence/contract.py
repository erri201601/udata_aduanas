"""Las reglas que una decisión debe cumplir para ser defendible.

Los constructores de `builder` garantizan que cada pieza de evidencia esté
completa. Este módulo verifica lo otro: que el CONJUNTO de evidencias sostiene
de verdad la afirmación, y en la fecha correcta.

Son cosas distintas. Se puede tener cinco evidencias impecables y aun así estar
citando una norma que no regía cuando ocurrió la operación.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.evidence.errors import (
    EvidenceOutOfValidityError,
    NotLegalBasisError,
    SyntheticLegalBasisError,
    UnsupportedClaimError,
)
from core.evidence.kinds import LEGAL_BASIS_KINDS, EvidenceKind

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from core.evidence.types import Evidence


def assert_legal_basis(evidences: Sequence[Evidence], *, claim: str) -> None:
    """Exige al menos una fuente jurídica recuperada para una afirmación legal.

    Es la regla que abre el §8.1 del maestro, en código: prohibido decir
    "según la ley..." si no existe una fuente recuperada.

    Un caso comparable de CBP o EBTI no basta y se rechaza explícitamente: una
    resolución extranjera puede orientar la interpretación, pero no obliga en
    México (§11).

    Una norma SINTÉTICA tampoco, y ese error se reporta aparte: significa que
    el contenido citado no existe, no que se usó el tipo equivocado.

    Raises:
        UnsupportedClaimError: si no hay ninguna evidencia.
        SyntheticLegalBasisError: si la única fuente jurídica es sintética.
        NotLegalBasisError: si hay evidencias pero ninguna es fundamento.
    """
    if not evidences:
        raise UnsupportedClaimError(claim)

    if any(e.is_legal_basis for e in evidences):
        return

    # Antes que nada, el caso sintético: si llegó una LEGAL_SOURCE y lo único
    # que la descalifica es su origen, decirlo con precisión. Un
    # `NotLegalBasisError` aquí diría "LEGAL_SOURCE no es fundamento", que es
    # falso y desconcertante para quien lo lea en un log.
    sintetica = next(
        (e for e in evidences if e.kind in LEGAL_BASIS_KINDS and e.is_synthetic),
        None,
    )
    if sintetica is not None:
        documento = sintetica.document_ref.document if sintetica.document_ref else sintetica.summary
        raise SyntheticLegalBasisError(documento)

    # Señalar el tipo más engañoso de los presentes: un COMPARABLE parece
    # fundamento y no lo es, y ese es el error que de verdad queremos delatar.
    culpable = next(
        (e.kind for e in evidences if e.kind is EvidenceKind.COMPARABLE),
        evidences[0].kind,
    )
    raise NotLegalBasisError(culpable)


def assert_temporal_validity(evidences: Sequence[Evidence], *, operation_date: date) -> None:
    """Exige que toda norma citada estuviera vigente en la fecha de la operación.

    §14 del maestro: nunca evaluar una operación histórica con regulación
    posterior. Sin esta comprobación, el sistema produciría hallazgos falsos
    con toda la apariencia de estar fundados — el peor resultado posible,
    porque son los que nadie cuestiona.

    Sólo restringe a las evidencias temporales: una salida de modelo o un caso
    comparable no tienen vigencia y no limitan la fecha.

    Raises:
        EvidenceOutOfValidityError: en la primera norma fuera de vigencia.
    """
    for e in evidences:
        if e.valid_from is None or e.covers(operation_date):
            continue
        documento = e.document_ref.document if e.document_ref else e.summary
        raise EvidenceOutOfValidityError(
            operation_date=operation_date,
            valid_from=e.valid_from,
            valid_to=e.valid_to,
            document=documento,
        )


def assert_defensible(
    evidences: Sequence[Evidence],
    *,
    claim: str,
    operation_date: date,
) -> None:
    """Ambas comprobaciones, en el orden en que importan.

    Primero que exista fundamento, después que ese fundamento aplicara a la
    fecha. Al revés se obtendría un error de vigencia sobre normas que ni
    siquiera sostenían la afirmación, que confunde más de lo que ayuda.
    """
    assert_legal_basis(evidences, claim=claim)
    assert_temporal_validity(evidences, operation_date=operation_date)
