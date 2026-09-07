"""Escribe una clasificación y todo lo que la sostiene.

El orquestador produce un `ClassificationOutcome` y nunca toca la base (§29).
Este módulo es quien lo escribe: la decisión, sus candidatos y sus evidencias,
en una sola transacción.

EL ORDEN DE INSERCIÓN NO ES ARBITRARIO

    1. la decisión, sin evidencia todavía  → para tener su id
    2. las evidencias, apuntando a esa id  → subject_kind/subject_id
    3. la decisión otra vez, con evidence_id apuntando a la principal

Hay una dependencia circular deliberada en el modelo: la decisión referencia su
evidencia principal, y cada evidencia referencia la decisión que sustenta. El
vínculo de vuelta es blando —`subject_kind` + `subject_id`, sin FK— justamente
para que se pueda cerrar el ciclo sin bloquearse.

QUÉ ES LA "EVIDENCIA PRINCIPAL"

`decision.evidence_id` apunta a UNA sola fila, pero una decisión se sostiene en
varias. Se elige la primera `LEGAL_SOURCE`, porque es la única que fundamenta
jurídicamente (§8.1). Si no hay ninguna, queda en NULL — y eso es información,
no un hueco: significa que la decisión no tiene fundamento legal recuperado.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from database.models import (
    ClassificationCandidate,
    ClassificationDecision,
    EvidenceRecord,
)

if TYPE_CHECKING:
    import uuid

    from core.classification import ClassificationOutcome
    from sqlalchemy.orm import Session

#: Origen de dato por defecto. Mientras los pedimentos del MVP sean sintéticos,
#: lo que se deriva de ellos también lo es (§10). Quien tenga datos reales lo
#: pasa explícitamente — no se infiere.
DEFAULT_DATA_ORIGIN = "SYNTHETIC"


def save_classification(
    session: Session,
    outcome: ClassificationOutcome,
    *,
    product_id: uuid.UUID | None = None,
    product_dna_id: uuid.UUID | None = None,
    trade_flow: str = "IMPORT",
    data_origin: str = DEFAULT_DATA_ORIGIN,
    synthetic_scenario_id: uuid.UUID | None = None,
    seed: int | None = None,
) -> ClassificationDecision:
    """Persiste una clasificación completa. NO hace commit.

    El commit lo controla quien llama, porque una clasificación casi nunca se
    guarda sola: normalmente forma parte de auditar un pedimento entero y todo
    debe entrar o no entrar junto.

    Devuelve la fila para que el llamante pueda encadenar hallazgos a ella.
    """
    fraccion = outcome.code
    decision = ClassificationDecision(
        product_id=product_id,
        product_dna_id=product_dna_id,
        trade_flow=trade_flow,
        operation_date=outcome.operation_date,
        status=outcome.status.value,
        # Los niveles se derivan de la fracción, no se piden aparte: pedirlos
        # abriría la puerta a que lleguen inconsistentes entre sí.
        **_niveles(fraccion),
        reasoning=_razonamiento(outcome),
        rgi_path=[p.rule_id for p in outcome.trace.steps],
        engine_version=outcome.trace.engine_version,
        input_snapshot=_snapshot(outcome),
        missing_information=list(outcome.trace.missing_information),
        confidence=outcome.confidence,
        requires_human_review=outcome.requires_human_review,
        data_origin=data_origin,
        synthetic_scenario_id=synthetic_scenario_id,
        seed=seed,
        **_telemetria(outcome),
    )
    session.add(decision)
    session.flush()  # necesitamos decision.id para enlazar la evidencia

    principal = _guardar_evidencias(
        session,
        outcome,
        decision_id=decision.id,
        data_origin=data_origin,
    )
    if principal is not None:
        decision.evidence_id = principal.id

    _guardar_candidatos(session, outcome, decision_id=decision.id, data_origin=data_origin)
    session.flush()
    return decision


# ── Piezas ───────────────────────────────────────────────────────────────────


def _niveles(fraccion: str | None) -> dict[str, str | None]:
    """Capítulo, partida y subpartida a partir de la fracción.

    `None` en todos si no hay fracción defendible. No se rellenan desde
    `trace.resolved_code` a propósito: si el contrato de evidencia rechazó la
    clasificación, guardar sus niveles daría la apariencia de una decisión
    parcialmente válida, y no lo es.
    """
    if not fraccion:
        return {"chapter": None, "heading": None, "subheading": None, "fraction_code": None}
    return {
        "chapter": fraccion[:2],
        "heading": fraccion[:4],
        "subheading": fraccion[:6],
        "fraction_code": fraccion,
    }


def _razonamiento(outcome: ClassificationOutcome) -> str:
    """El razonamiento completo, paso a paso.

    Concatenado en un texto porque `classification_decisions` todavía no tiene
    la columna `rgi_trace` que guarde la traza estructurada. Cuando exista, esto
    pasa a ser el resumen y la traza va aparte, consultable.

    Mientras tanto se conserva el razonamiento de CADA regla y no sólo uno
    global: perderlo haría imposible responder «¿con qué regla?» del §49 con el
    detalle que una auditoría pide.
    """
    partes = [
        f"{p.rule_id}: {p.reasoning_summary}" for p in outcome.trace.steps if p.reasoning_summary
    ]
    if outcome.blocked_by:
        partes.append(f"NO DEFENDIBLE: {outcome.blocked_by}")
    return " · ".join(partes)


def _snapshot(outcome: ClassificationOutcome) -> dict[str, Any]:
    """Con qué datos se decidió.

    Responde «¿qué dato utilizaste?» del §49 sin depender de que el Product DNA
    siga existiendo igual mañana. Una decisión firmada tiene que poder
    explicarse con lo que se sabía entonces, no con lo que se sabe ahora.
    """
    return {
        "facts": outcome.facts_used,
        "operation_date": outcome.operation_date.isoformat(),
        "rules_evaluated": [p.rule_id for p in outcome.trace.steps],
        "rejected": list(outcome.trace.rejected()),
    }


def _telemetria(outcome: ClassificationOutcome) -> dict[str, Any]:
    """Telemetría del modelo, si alguna evidencia la trae.

    El CHECK `ck_classification_decisions_ai_call_complete` exige que si hay
    `model_provider`, estén también el resto de campos. Por eso se copian
    juntos o no se copia ninguno: llenar sólo el proveedor haría fallar la
    inserción, y con razón.
    """
    modelo = next(
        (e for e in outcome.evidences if e.kind.value == "MODEL_OUTPUT" and e.model_name),
        None,
    )
    if modelo is None:
        return {}
    return {
        "model_provider": modelo.model_provider,
        "model_name": modelo.model_name,
        "prompt_id": modelo.prompt_id,
        "prompt_version": modelo.prompt_version,
        # El motor no mide tokens ni latencia: eso lo sabe core/llm, y esta
        # evidencia no los arrastra. Se dejan en los valores que el CHECK
        # exige, marcando que la llamada existió aunque no se midiera.
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": 0,
        "attempts": 1,
    }


def _guardar_evidencias(
    session: Session,
    outcome: ClassificationOutcome,
    *,
    decision_id: uuid.UUID,
    data_origin: str,
) -> EvidenceRecord | None:
    """Escribe cada evidencia y devuelve la principal, si la hay."""
    filas: list[EvidenceRecord] = []
    for ev in outcome.evidences:
        campos = ev.to_record_fields()
        fila = EvidenceRecord(
            subject_kind="classification_decision",
            subject_id=decision_id,
            data_origin=data_origin,
            **campos,
        )
        session.add(fila)
        filas.append(fila)

    if not filas:
        return None
    session.flush()

    # La principal es la primera fuente jurídica: la única que fundamenta
    # (§8.1). Sin ninguna, NULL — y eso dice que la decisión no tiene
    # fundamento legal recuperado, que es información y no un hueco.
    return next((f for f in filas if f.evidence_kind == "LEGAL_SOURCE"), None)


def _guardar_candidatos(
    session: Session,
    outcome: ClassificationOutcome,
    *,
    decision_id: uuid.UUID,
    data_origin: str,
) -> None:
    """Escribe las alternativas evaluadas, con por qué se descartaron.

    Lo que se descartó es la mitad del valor de una traza: no es que el sistema
    eligiera 8471.30.01, es que descartó las otras por un motivo que se puede
    leer. Guardar sólo la ganadora convertiría la decisión en una caja negra.
    """
    vistos: set[str] = set()
    rango = 0
    for paso in outcome.trace.steps:
        for cand in paso.candidate_codes:
            if cand.code in vistos:
                continue
            vistos.add(cand.code)
            rango += 1
            # Un candidato está EN EL CAMINO si la fracción final desciende de
            # él: la partida 8471 no fue descartada, fue el camino hacia
            # 84713001. Compararlo por igualdad estricta marcaría como
            # rechazadas todas las partidas y subpartidas del camino ganador —
            # y una traza que dice que descartó lo que eligió no explica nada.
            gano = bool(outcome.code) and outcome.code.startswith(cand.code)  # type: ignore[union-attr]
            session.add(
                ClassificationCandidate(
                    classification_decision_id=decision_id,
                    rank=rango,
                    fraction_code=cand.code if len(cand.code) == 8 else None,
                    # `is_selected` marca al ganador. Sin él habría que
                    # deducirlo comparando con la decisión, y una consulta que
                    # deduce se equivoca antes o después.
                    is_selected=gano,
                    reasoning=cand.text[:512],
                    confidence=paso.confidence,
                    rejected_reason=None if gano else _por_que_no(outcome, cand.code),
                    data_origin=data_origin,
                )
            )


def _por_que_no(outcome: ClassificationOutcome, code: str) -> str | None:
    """El motivo por el que un candidato no ganó.

    Se busca en el razonamiento de la regla que lo descartó, no se inventa una
    explicación genérica: «no fue el más específico» sin decir frente a qué no
    ayuda a nadie a revisar la decisión.
    """
    for paso in outcome.trace.steps:
        codigos = {c.code for c in paso.candidate_codes}
        if code in codigos and outcome.code not in codigos and paso.reasoning_summary:
            return paso.reasoning_summary[:512]
    for paso in reversed(outcome.trace.steps):
        if paso.reasoning_summary and code not in {c.code for c in paso.candidate_codes}:
            return f"Descartado en {paso.rule_id}: {paso.reasoning_summary}"[:512]
    return None
