"""Vocabulario cerrado de tipos de evidencia y qué exige cada uno.

No toda evidencia se sustenta igual. Una norma recuperada del DOF y la salida
de un modelo de lenguaje son dos cosas distintas, y tratarlas como una sola es
exactamente el error que hace indefendible un sistema como este: acaba dando
la misma autoridad a "lo dice la Ley Aduanera" y a "lo dedujo un modelo".

Cada tipo declara qué campos son obligatorios. `core.evidence.builder` los
impone al construir, no al insertar en la base: el error tiene que llegar donde
está el defecto.

Añadir un tipo es un cambio de contrato central. Lo aprueba Persona 1 (§9).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class EvidenceKind(StrEnum):
    """De qué naturaleza es el respaldo de una afirmación."""

    LEGAL_SOURCE = "LEGAL_SOURCE"
    """Una norma recuperada: LIGIE, Ley Aduanera, RGCE, NOM, Anexo 22.

    Es el único tipo que constituye fundamento jurídico mexicano.
    """

    MODEL_OUTPUT = "MODEL_OUTPUT"
    """Un modelo de lenguaje produjo el dato.

    Sirve para interpretar y explicar. NO es fundamento jurídico por sí solo:
    una afirmación legal sostenida sólo por esto viola §8.1 del maestro.
    """

    DETERMINISTIC = "DETERMINISTIC"
    """Una regla de código la produjo, sin modelo de por medio.

    Cálculos de Money Finder, divergencias del Pedimento Espejo, reglas del
    RGI que se resuelven sin interpretación.
    """

    HUMAN = "HUMAN"
    """Una persona lo revisó y lo validó.

    Es la evidencia de mayor peso del sistema y la que alimenta la evaluación
    de §39. Corresponde a `data_origin = HUMAN_VALIDATED`.
    """

    COMPARABLE = "COMPARABLE"
    """Un caso internacional comparable: CBP CROSS, EBTI, opiniones WCO.

    Apoyo interpretativo únicamente. NUNCA fundamento jurídico mexicano: una
    resolución estadounidense no obliga en México, y el §11 del maestro
    prohíbe convertir HTS10 o CN/TARIC directamente a TIGIE.
    """


#: Tipos que pueden sostener una afirmación jurídica por sí solos.
#:
#: Deliberadamente sólo uno. HUMAN valida una interpretación, pero la norma que
#: la sustenta sigue teniendo que estar recuperada y citada; por eso tampoco
#: aparece aquí.
LEGAL_BASIS_KINDS: Final[frozenset[EvidenceKind]] = frozenset({EvidenceKind.LEGAL_SOURCE})

#: Campos obligatorios por tipo. `builder` los exige al construir.
#:
#: Son los que permiten responder las diez preguntas de §49 para ese tipo. Si
#: falta uno, la evidencia no puede defenderse y no debe existir.
REQUIRED_FIELDS: Final[dict[EvidenceKind, frozenset[str]]] = {
    # De qué fuente, qué versión, cuándo era vigente, cómo verificar que no
    # cambió: sin los cuatro, la cita no es comprobable.
    EvidenceKind.LEGAL_SOURCE: frozenset(
        {"source_id", "document_ref", "valid_from", "content_hash"}
    ),
    # Qué modelo, con qué prompt y en qué versión. Sin esto no se puede
    # reproducir ni auditar una salida.
    EvidenceKind.MODEL_OUTPUT: frozenset(
        {"model_provider", "model_name", "prompt_id", "prompt_version"}
    ),
    # Qué regla y qué versión del motor la ejecutó.
    EvidenceKind.DETERMINISTIC: frozenset({"rule_id", "engine_version"}),
    # Quién y cuándo. Sin autor, una validación humana no vale nada.
    EvidenceKind.HUMAN: frozenset({"reviewer", "reviewed_at"}),
    # De qué jurisdicción y qué caso. La jurisdicción es obligatoria porque es
    # justo lo que impide confundirlo con fundamento mexicano.
    EvidenceKind.COMPARABLE: frozenset({"jurisdiction", "case_ref", "document_ref"}),
}
