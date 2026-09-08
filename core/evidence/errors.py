"""Errores del Evidence Contract.

Son excepciones propias y no `ValueError` genéricos a propósito: quien los
capture tiene que poder distinguir "le falta un campo" de "la norma no estaba
vigente" de "intentaron usar un caso extranjero como fundamento". Los tres
significan cosas distintas para quien audita una decisión.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from core.evidence.kinds import EvidenceKind


class EvidenceError(Exception):
    """Raíz de los errores del contrato de evidencia."""


class IncompleteEvidenceError(EvidenceError):
    """Falta un campo obligatorio para ese tipo de evidencia.

    Se lanza al CONSTRUIR, no al persistir: el error debe llegar donde está el
    defecto, no a la capa de base de datos donde ya se perdió el contexto.
    """

    def __init__(self, kind: EvidenceKind, missing: frozenset[str] | set[str]) -> None:
        self.kind = kind
        self.missing = frozenset(missing)
        faltantes = ", ".join(sorted(self.missing))
        super().__init__(
            f"Evidencia {kind.value} incompleta: faltan {faltantes}. "
            f"Sin esos campos la decisión no puede defenderse (§8.1, §17)."
        )


class EvidenceOutOfValidityError(EvidenceError):
    """La norma citada no estaba vigente en la fecha de la operación.

    Es el error que impide juzgar una operación de 2024 con una regla de 2026
    (§14 del maestro). Silenciarlo produciría hallazgos falsos con apariencia
    de fundamento.
    """

    def __init__(
        self,
        operation_date: date,
        valid_from: date,
        valid_to: date | None,
        document: str,
    ) -> None:
        self.operation_date = operation_date
        self.valid_from = valid_from
        self.valid_to = valid_to
        self.document = document
        hasta = valid_to.isoformat() if valid_to else "vigente"
        super().__init__(
            f"'{document}' rige de {valid_from.isoformat()} a {hasta}, "
            f"y la operación es del {operation_date.isoformat()}. "
            f"No se puede evaluar una operación con regulación que no le aplicaba (§14)."
        )


class NotLegalBasisError(EvidenceError):
    """Se intentó sostener una afirmación jurídica con evidencia que no lo es.

    El caso típico es un precedente de CBP CROSS o EBTI. Son útiles para
    interpretar, pero una resolución extranjera no obliga en México y el §11
    prohíbe convertir HTS10 o CN/TARIC directamente a TIGIE.
    """

    def __init__(self, kind: EvidenceKind) -> None:
        self.kind = kind
        super().__init__(
            f"Una evidencia {kind.value} no es fundamento jurídico mexicano. "
            f"Puede acompañar una interpretación, pero la afirmación legal "
            f"necesita al menos una fuente LEGAL_SOURCE recuperada (§8.1)."
        )


class SyntheticLegalBasisError(EvidenceError):
    """Se intentó fundamentar una afirmación jurídica con una norma SINTÉTICA.

    Distinto de `NotLegalBasisError` a propósito, aunque los dos digan "esto no
    fundamenta". Ese señala haber usado el tipo equivocado —un precedente
    extranjero, la salida de un modelo—, algo que un revisor entiende y
    corrige. Este señala que el contenido citado no existe: es ley inventada
    con apariencia de recuperada, y es el peor fallo que puede tener el
    sistema, porque el resultado sale marcado como defendible.

    El caso realista no es malicioso: un fixture de pruebas del RAG, un
    documento sembrado para poblar una demo, una fracción del seed conviviendo
    con la tarifa real.
    """

    def __init__(self, document: str) -> None:
        self.document = document
        super().__init__(
            f"'{document}' tiene data_origin=SYNTHETIC y no puede fundamentar "
            f"una afirmación jurídica. Una norma generada cumple los mismos "
            f"campos que una recuperada —incluido el content_hash— y aun así "
            f"no es ley (regla 4 de CLAUDE.md, §10). Devuelve "
            f"INSUFFICIENT_INFORMATION o HUMAN_REVIEW_REQUIRED."
        )


class UnsupportedClaimError(EvidenceError):
    """Una decisión jurídica llegó sin ninguna evidencia que la sostenga.

    Es la traducción en código de la regla que abre el §8.1: prohibido decir
    "según la ley..." si no existe una fuente recuperada.
    """

    def __init__(self, subject: str) -> None:
        self.subject = subject
        super().__init__(
            f"'{subject}' no tiene evidencia que lo sustente. "
            f"Sin fuente recuperada no hay afirmación jurídica (§8.1). "
            f"Devuelve INSUFFICIENT_INFORMATION o HUMAN_REVIEW_REQUIRED."
        )
