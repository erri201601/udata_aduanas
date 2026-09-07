"""RGI Engine — máquina de evaluación de las Reglas Generales de Interpretación.

§18 del maestro: "No implementar clasificación como un prompt gigante.
Construir una máquina de evaluación." Cada regla se evalúa por separado, con su
estado explícito, y la traza muestra no sólo qué se decidió sino qué se
descartó y por qué.

USO

    from core.rgi_engine import ClassificationContext, ProductFact, classify

    contexto = ClassificationContext(
        description="Computadora portátil de 16 pulgadas",
        operation_date=date(2024, 3, 15),
        facts=(
            ProductFact(name="function", value="tratamiento de datos", status="OBSERVED"),
            ProductFact(name="weight", value="1.4 kg", status="EXTRACTED"),
        ),
        search_terms=("máquina automática para tratamiento de datos",),
    )

    traza = classify(contexto, catalog=catalogo, notes=notas)

    traza.final_status      # RESOLVED | INSUFFICIENT_INFORMATION | HUMAN_REVIEW_REQUIRED
    traza.resolved_code     # '8471.30.01' o None
    traza.applied_rule      # 'RGI-6'
    traza.rejected()        # por qué se descartó cada alternativa

DEPENDENCIAS INYECTADAS

El motor no toca la base de datos ni llama a ningún proveedor de IA. Declara lo
que necesita en `ports.py` y alguien se lo pasa:

    TariffCatalog   la nomenclatura vigente en una fecha   (Persona 2)
    LegalNotes      notas de sección y capítulo            (Persona 2)
    Interpreter     ayuda de un LLM, OPCIONAL              (Persona 3)

Eso permite construirlo y probarlo sin esperar a que existan los datos reales,
y cumple §29: `core/` no importa la capa de persistencia.

QUÉ NO HACE ESTA VERSIÓN

RGI 2, 4 y 5 no están implementadas. NO se saltan en silencio: detectan si sus
precondiciones se cumplen y devuelven `HUMAN_REVIEW_REQUIRED`. Una regla no
implementada que devolviera `CONTINUE` dejaría pasar mercancías que necesitaban
justo esa regla, con el resultado peor posible: una clasificación equivocada
con apariencia de fundada.

Tampoco resuelve el NICO, ni emite `EvidenceRecord`. Lo segundo es deliberado:
el motor produce la traza y el orquestador la convierte en evidencia con
`core.evidence.builder`, para que `core/rgi_engine` no dependa de
`core/evidence`.
"""

from __future__ import annotations

from core.rgi_engine.context import ClassificationContext, ProductFact, TariffCandidate
from core.rgi_engine.engine import ENGINE_VERSION, HEADING_RULES, classify
from core.rgi_engine.ports import Interpreter, LegalNotes, TariffCatalog
from core.rgi_engine.results import ClassificationTrace, RGIResult
from core.rgi_engine.rules import RGI1, RGI2, RGI3A, RGI3B, RGI3C, RGI4, RGI5, RGI6, RGIRule
from core.rgi_engine.states import TERMINAL, RGIStatus

__all__ = [
    "ENGINE_VERSION",
    "HEADING_RULES",
    "RGI1",
    "RGI2",
    "RGI3A",
    "RGI3B",
    "RGI3C",
    "RGI4",
    "RGI5",
    "RGI6",
    "TERMINAL",
    "ClassificationContext",
    "ClassificationTrace",
    "Interpreter",
    "LegalNotes",
    "ProductFact",
    "RGIResult",
    "RGIRule",
    "RGIStatus",
    "TariffCandidate",
    "TariffCatalog",
    "classify",
]
