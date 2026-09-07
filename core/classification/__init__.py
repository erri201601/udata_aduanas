"""Classification Orchestrator — el eslabón que une los cuatro motores.

    Product DNA  →  RGI Engine  →  Evidence  →  Money Finder

Cada motor sabe hacer una cosa y ninguno conoce a los demás: el Product DNA no
sabe de clasificación, el RGI no sabe de evidencia, el Money Finder no sabe de
fracciones. Esa ignorancia mutua es deliberada — permite probarlos y cambiarlos
por separado — y este módulo es el único que los ve a todos.

Cierra el vertical slice del §42.

USO

    from core.classification import classify_product, with_money_impact

    resultado = classify_product(
        dna,
        operation_date=date(2024, 3, 15),
        catalog=catalogo,     # de Persona 2, sobre la tarifa real
        notes=notas,
        interpreter=interprete,   # opcional
        search_terms=("máquina automática para tratamiento de datos",),
        legal_refs=[(doc_ligie, date(2022, 7, 7), "sha256:...")],
    )

    resultado.code                    # la fracción, sólo si es defendible
    resultado.requires_human_review
    resultado.dossier.is_complete     # ¿contesta las diez preguntas del §49?
    resultado.explain()

    # Cuando hay un pedimento contra el que comparar:
    con_dinero = with_money_impact(
        resultado,
        transaction_value=valor,
        declared_rates=tasas_declaradas,
        expected_rates=tasas_esperadas,
    )
    con_dinero.impact.direction   # OMISION | SOBREPAGO | SIN_DIFERENCIA

LA DECISIÓN QUE DEFINE ESTE MÓDULO

Que el RGI resuelva un código NO significa que sea defendible. El contrato de
evidencia puede rechazarlo por falta de fundamento o por vigencia, y en ese
caso `outcome.code` devuelve `None` aunque `trace.resolved_code` tenga valor.

Es la diferencia entre «el motor llegó a 8471.30.01» y «8471.30.01 se puede
sostener ante una auditoría». Sólo la segunda sirve para declarar un pedimento,
y sólo la segunda sale de aquí.

QUÉ NO HACE

No persiste nada. `to_decision_fields()` devuelve un dict plano y quien escriba
la fila ensambla (§29). Tampoco resuelve el NICO ni construye el Pedimento
Espejo.
"""

from __future__ import annotations

from core.classification.orchestrator import classify_product, with_money_impact
from core.classification.result import ClassificationOutcome

__all__ = [
    "ClassificationOutcome",
    "classify_product",
    "with_money_impact",
]
