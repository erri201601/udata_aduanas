"""Audit Engine — convierte divergencias en hallazgos accionables.

    Pedimento Espejo  →  Money Finder  →  Evidence  →  Finding
       qué difiere       cuánto cuesta    con qué      accionable

Es lo que convierte «la fracción está mal» en «la fracción está mal y son
11,600 pesos omitidos, según la LIGIE vigente ese día». La primera frase se
ignora; la segunda se corrige.

USO

    from core.audit import audit

    informe = audit(
        comparacion,                    # de core.shadow
        transaction_value=valor,
        declared_rates=tasas_declaradas,
        expected_rates=tasas_esperadas,
        evidences=resultado.evidences,  # del orquestador
    )

    informe.worst_severity      # CRITICAL | HIGH | MEDIUM | LOW | INFO
    informe.total_exposure      # contribuciones omitidas
    informe.total_recoverable   # pagado de más
    informe.opportunities       # los sobrepagos
    informe.is_complete         # ¿se auditó TODO?
    informe.summary()

TRES DECISIONES QUE DEFINEN EL MÓDULO

**Sólo se cuantifica lo que cambia lo que se paga.** Una NOM faltante detiene
la mercancía pero no altera las contribuciones. Inventarle un monto para que la
tabla se vea completa sería lo que el §36 prohíbe: un número plausible es peor
que un hueco declarado, porque el hueco se ve y el número no.

**El dinero puede subir la severidad, nunca bajarla.** Una fracción equivocada
de un millón merece más atención que una de mil, pero un NOM faltante detiene
la mercancía valga lo que valga. Rebajarlo por el monto sería confundir
«barato» con «leve».

**El total no es la suma de los hallazgos.** Varias divergencias pueden
explicar la misma diferencia de contribuciones —una fracción equivocada y un
valor equivocado producen un único delta—, así que sumarlos contaría el mismo
dinero dos veces.

QUÉ NO HACE

No persiste. `to_finding_fields()` devuelve un dict plano (§29). No decide si
un sobrepago es recuperable: eso es del Opportunity Finder, que además tiene
que verificar si la vía de recuperación sigue abierta.
"""

from __future__ import annotations

from core.audit.engine import CUANTIFICABLES, audit
from core.audit.findings import AuditReport, Finding, empty_report
from core.audit.severity import ESCALA, UMBRALES, adjust, severity_for_amount

__all__ = [
    "CUANTIFICABLES",
    "ESCALA",
    "UMBRALES",
    "AuditReport",
    "Finding",
    "adjust",
    "audit",
    "empty_report",
    "severity_for_amount",
]
