"""Las diez preguntas del §49, ensambladas a partir de una decisión.

El §49 del maestro cierra diciendo que si ADUANERO OS no puede responder estas
diez preguntas, la funcionalidad no está terminada. Este módulo las convierte
en algo ejecutable: si `answer_all()` devuelve un `UNKNOWN`, es que falta algo,
y se ve exactamente qué.

Es la prueba de fuego del contrato de evidencia. Un diseño que no las contesta
está incompleto por definición, no por opinión.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from core.evidence.kinds import EvidenceKind

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from core.evidence.types import Evidence

#: Marcador para lo que no se puede responder con la evidencia disponible.
#: Se devuelve esto y NO una cadena vacía ni un valor plausible: §36 prohíbe
#: rellenar huecos, y un "—" silencioso se confunde con "no aplica".
UNKNOWN: str = "UNKNOWN"


class Dossier(BaseModel):
    """Respuesta a las diez preguntas del §49 sobre una decisión concreta.

    Es lo que se enseña en la Evidence UI y lo que se entrega si alguien
    audita una clasificación.
    """

    model_config = ConfigDict(frozen=True)

    what: str
    """¿QUÉ DETECTASTE?"""

    why: str
    """¿POR QUÉ?"""

    which_rule: str
    """¿CON QUÉ REGLA?"""

    which_source: list[str]
    """¿CON QUÉ FUENTE?"""

    source_version: list[str]
    """¿QUÉ VERSIÓN DE ESA FUENTE? — content_hash y fecha de publicación."""

    validity: list[str]
    """¿CUÁNDO ERA VIGENTE?"""

    data_used: dict[str, Any]
    """¿QUÉ DATO UTILIZASTE?"""

    confidence: Decimal | None
    """¿CUÁNTA CONFIANZA TIENES?"""

    money_impact: str
    """¿CUÁNTO DINERO REPRESENTA?"""

    requires_human_review: bool
    """¿REQUIERE REVISIÓN HUMANA?"""

    unanswered: list[str] = Field(default_factory=list)
    """Preguntas que la evidencia disponible no alcanza a responder.

    Que esta lista no esté vacía no es un fallo del ensamblado: es el
    ensamblado diciendo la verdad sobre lo que falta.
    """

    @property
    def is_complete(self) -> bool:
        """¿Contesta las diez? Si no, la funcionalidad no está terminada (§49)."""
        return not self.unanswered


def answer_all(
    *,
    what: str,
    evidences: Sequence[Evidence],
    operation_date: date,
    confidence: Decimal | None = None,
    money_impact: str | None = None,
    requires_human_review: bool = True,
    data_used: dict[str, Any] | None = None,
) -> Dossier:
    """Ensambla las diez respuestas a partir de las evidencias de una decisión.

    `requires_human_review` es `True` por defecto, igual que en la base: el
    sistema falla hacia la cautela. Bajarlo es una decisión explícita del motor
    cuando tiene evidencia suficiente, nunca un descuido.
    """
    legales = [e for e in evidences if e.kind is EvidenceKind.LEGAL_SOURCE]
    reglas = [e for e in evidences if e.kind is EvidenceKind.DETERMINISTIC]
    modelos = [e for e in evidences if e.kind is EvidenceKind.MODEL_OUTPUT]
    comparables = [e for e in evidences if e.kind is EvidenceKind.COMPARABLE]

    sin_responder: list[str] = []

    # ¿POR QUÉ? — el razonamiento, en el orden en que pesa: la norma primero,
    # la regla después, la interpretación del modelo al final.
    porques = [e.summary for e in (*legales, *reglas, *modelos) if e.summary]
    why = " · ".join(porques) if porques else UNKNOWN
    if why is UNKNOWN:
        sin_responder.append("why")

    # ¿CON QUÉ REGLA?
    if reglas:
        which_rule = " · ".join(f"{e.rule_id} (motor {e.engine_version})" for e in reglas)
    elif modelos:
        which_rule = " · ".join(f"{e.prompt_id} v{e.prompt_version}" for e in modelos)
    else:
        which_rule = UNKNOWN
        sin_responder.append("which_rule")

    # ¿CON QUÉ FUENTE? Los comparables se etiquetan con su jurisdicción para
    # que nadie los lea como fundamento mexicano.
    fuentes = [
        f"{e.document_ref.document}"
        + (f", {e.document_ref.article}" if e.document_ref and e.document_ref.article else "")
        for e in legales
        if e.document_ref
    ]
    fuentes += [f"[comparable {e.jurisdiction}] {e.case_ref}" for e in comparables]
    if not fuentes:
        sin_responder.append("which_source")

    # ¿QUÉ VERSIÓN DE ESA FUENTE?
    versiones = []
    for e in legales:
        partes = []
        if e.document_ref and e.document_ref.published_at:
            partes.append(f"publicada {e.document_ref.published_at.isoformat()}")
        if e.content_hash:
            # Truncar el hash entero dejaría casi sólo el prefijo del
            # algoritmo ("sha256:aaaa1"), que no identifica ninguna versión.
            # Lo que distingue un documento de otro es el digest.
            digest = e.content_hash.split(":", 1)[-1]
            partes.append(f"hash {digest[:16]}")
        versiones.append(
            f"{e.document_ref.document if e.document_ref else e.summary}: "
            + (", ".join(partes) if partes else UNKNOWN)
        )
    # Sin fuentes legales, o con fuentes sin hash, no se puede decir QUÉ VERSIÓN
    # de la norma se usó — que es media pregunta del §49.
    if not legales or not any(e.content_hash for e in legales):
        sin_responder.append("source_version")

    # ¿CUÁNDO ERA VIGENTE?
    vigencias = [
        f"{e.document_ref.document if e.document_ref else e.summary}: "
        f"{e.valid_from.isoformat() if e.valid_from else UNKNOWN} → "
        f"{e.valid_to.isoformat() if e.valid_to else 'vigente'}"
        + ("" if e.covers(operation_date) else "  ⚠ NO CUBRE LA OPERACIÓN")
        for e in legales
    ]
    if not vigencias:
        sin_responder.append("validity")

    # ¿QUÉ DATO UTILIZASTE?
    datos: dict[str, Any] = dict(data_used or {})
    for e in reglas:
        datos.update(e.inputs)
    if not datos:
        sin_responder.append("data_used")

    # ¿CUÁNTA CONFIANZA? La explícita gana; si no, la menor de las evidencias:
    # una cadena no es más fuerte que su eslabón más débil.
    if confidence is None:
        confianzas = [e.confidence for e in evidences if e.confidence is not None]
        confidence = min(confianzas) if confianzas else None
    if confidence is None:
        sin_responder.append("confidence")

    # ¿CUÁNTO DINERO? Lo calcula Money Finder con Decimal; aquí sólo se cita.
    if money_impact is None:
        money_impact = UNKNOWN
        sin_responder.append("money_impact")

    return Dossier(
        what=what,
        why=why,
        which_rule=which_rule,
        which_source=fuentes or [UNKNOWN],
        source_version=versiones or [UNKNOWN],
        validity=vigencias or [UNKNOWN],
        data_used=datos,
        confidence=confidence,
        money_impact=money_impact,
        requires_human_review=requires_human_review,
        unanswered=sin_responder,
    )
