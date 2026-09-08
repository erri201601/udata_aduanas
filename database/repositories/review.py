"""Escribe una revisión de pedimento y todo lo que produjo.

`core.review` nunca toca la base (§29). Este módulo es quien escribe la corrida
del Espejo, sus hallazgos y sus oportunidades, en una sola transacción.

EL ORDEN IMPORTA

    1. `shadow_reviews`      → para tener su id
    2. `risk_findings`       → apuntando a esa revisión
    3. `opportunity_findings`

Sin el paso 1 los hallazgos quedan sin corrida y dos auditorías del mismo
pedimento —antes y después de una rectificación— mezclan sus resultados.

POR QUÉ SE ESCRIBE LA REVISIÓN AUNQUE NO HAYA HALLAZGOS

Una revisión sin hallazgos es información: dice que alguien miró y qué miró.
Sin la fila, `coverage_known` queda en `false` y la API no puede distinguir
«se revisó y salió limpio» de «nadie lo ha revisado» (§36).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.review import REVIEW_VERSION

from database.models import OpportunityFinding, RiskFinding, ShadowReview

if TYPE_CHECKING:
    import uuid

    from core.review import PedimentoReview
    from sqlalchemy.orm import Session

#: Mientras los pedimentos del MVP sean sintéticos, lo que se deriva de ellos
#: también lo es (§10). Quien tenga datos reales lo pasa explícitamente.
DEFAULT_DATA_ORIGIN = "SYNTHETIC"


def save_review(
    session: Session,
    review: PedimentoReview,
    *,
    pedimento_id: uuid.UUID,
    item_ids: dict[int, uuid.UUID] | None = None,
    data_origin: str = DEFAULT_DATA_ORIGIN,
) -> ShadowReview:
    """Persiste una revisión completa. NO hace commit — lo controla quien llama.

    `item_ids` mapea número de línea a id de partida, para que cada hallazgo
    apunte a la suya. Una línea que no esté en el mapa produce un hallazgo a
    nivel de pedimento, sin partida: es menos preciso, pero perder el hallazgo
    sería peor.
    """
    ids = item_ids or {}

    corrida = ShadowReview(
        pedimento_id=pedimento_id,
        is_complete=review.is_complete,
        unverifiable=list(review.unverifiable),
        engine_version=REVIEW_VERSION,
        data_origin=data_origin,
    )
    session.add(corrida)
    session.flush()

    for hallazgo in review.findings:
        divergencia = hallazgo.divergence
        session.add(
            RiskFinding(
                pedimento_id=pedimento_id,
                pedimento_item_id=ids.get(divergencia.line_number),
                shadow_review_id=corrida.id,
                finding_type=divergencia.kind.value,
                field=divergencia.field,
                declared_value=divergencia.declared_value,
                expected_value=divergencia.expected_value,
                severity=hallazgo.severity,
                # El motivo de la severidad va con el razonamiento: una
                # severidad elevada sin explicación es una decisión que nadie
                # puede revisar después.
                rationale=_razonamiento(divergencia.reasoning, hallazgo.severity_reason),
                impact_amount=hallazgo.impact_amount,
                impact_amount_currency=hallazgo.impact_currency,
                is_simulation=hallazgo.is_simulation,
                data_origin=data_origin,
            )
        )

    if review.opportunities is not None:
        for oportunidad in review.opportunities.opportunities:
            session.add(
                OpportunityFinding(
                    pedimento_id=pedimento_id,
                    pedimento_item_id=ids.get(oportunidad.line_number)
                    if oportunidad.line_number is not None
                    else None,
                    opportunity_type=oportunidad.kind.value,
                    status=oportunidad.status,
                    rationale=_con_condiciones(oportunidad.rationale, oportunidad.conditions),
                    # El sobrepago viaja con signo negativo desde el Money
                    # Finder; como ahorro se guarda en positivo, que es como se
                    # lee: "puedes recuperar 17,400", no "menos 17,400".
                    estimated_saving_amount=abs(oportunidad.estimated_saving)
                    if oportunidad.estimated_saving is not None
                    else None,
                    estimated_saving_amount_currency=oportunidad.currency,
                    is_simulation=oportunidad.is_simulation,
                    data_origin=data_origin,
                )
            )

    return corrida


def _razonamiento(base: str | None, motivo_severidad: str | None) -> str | None:
    if not motivo_severidad:
        return base
    if not base:
        return motivo_severidad
    return f"{base} · {motivo_severidad}"


def _con_condiciones(base: str, condiciones: tuple[str, ...]) -> str:
    """Las condiciones viajan con el razonamiento, no aparte.

    Una oportunidad sin lo que falta comprobar es un número que nadie sabe si
    puede cobrar (§23). El modelo no tiene columna propia para ellas, así que
    se escriben aquí antes que perderlas.
    """
    if not condiciones:
        return base
    pendientes = "; ".join(condiciones)
    return f"{base} · Falta comprobar: {pendientes}"
