"""Pedimento Espejo — lo declarado contra lo esperado.

§9.3: el sistema construye la operación que DEBERÍA declararse sin mirar la
declarada, y sólo después compara. Si mirara primero tendería a justificar lo
que ya está ahí, que es el sesgo que tiene un revisor humano y que la máquina
debería no tener.

USO

    from core.shadow import DeclaredItem, ExpectedItem, compare

    resultado = compare(
        declared=[DeclaredItem(line_number=1, fraction_code="84713099", ...)],
        expected=[ExpectedItem(line_number=1, fraction_code="84713001",
                               is_resolved=True, ...)],
        sku_history={"LAP-14-8GB": "84713001"},
    )

    resultado.has_findings
    resultado.worst_severity      # CRITICAL | HIGH | MEDIUM | LOW | INFO
    resultado.is_complete         # ¿se pudo verificar TODO?
    resultado.summary()

LA REGLA QUE GOBIERNA EL MÓDULO

Una divergencia sólo se emite cuando el sistema puede SOSTENER su expectativa.
Si la clasificación no llegó a ser defendible, no se acusa: se declara no
verificable.

Es la diferencia entre «la fracción declarada está mal» y «no pude comprobar la
fracción declarada». La primera acusa a un agente aduanal de un error que
acarrea multa y crédito fiscal; la segunda pide que alguien lo mire. Emitir la
primera sin fundamento destruye la confianza en el sistema más rápido de lo que
cualquier acierto la construye.

Por eso `unverifiable` va aparte de `divergences`: «no encontré nada mal» y «no
pude comprobarlo» son cosas distintas, y confundirlas haría que un pedimento
sin verificar pareciera limpio (§36).

QUÉ NO HACE

No calcula el impacto económico: eso es del Money Finder, y el Audit Engine los
une. No construye el `ExpectedItem` — lo arma quien tenga el Product DNA y la
clasificación, para que este módulo compare sin saber de dónde salió la
expectativa.
"""

from __future__ import annotations

from core.shadow.compare import (
    VALUE_TOLERANCE,
    compare,
    compare_item,
    comprobaciones_posibles,
)
from core.shadow.divergences import DEFAULT_SEVERITY, DivergenceType
from core.shadow.types import (
    DeclaredItem,
    Divergence,
    ExpectedItem,
    ShadowComparison,
    default_severity,
)

__all__ = [
    "DEFAULT_SEVERITY",
    "VALUE_TOLERANCE",
    "DeclaredItem",
    "Divergence",
    "DivergenceType",
    "ExpectedItem",
    "ShadowComparison",
    "compare",
    "compare_item",
    "comprobaciones_posibles",
    "default_severity",
]
