"""Copilot (§31): redactar sobre los pasajes recuperados, sin aportar nada.

El contrato está en `docs/adr/0010-contrato-del-copilot.md`. Lo que vive aquí
es lo que decide, y no depende de la API ni de ningún SDK (§29):

- `redactar`: pide la redacción a un `ModelProvider` y la valida;
- `validar`: extrae las citas `[n]` y cuenta las oraciones (código, no modelo);
- `faltantes_deterministas`: lo que falta y no hace falta preguntarle al modelo;
- `requiere_revision`: el punto 6 del ADR.
"""

from core.copilot.redaccion import (
    CITA_INEXISTENTE,
    PROMPT_ID,
    PROMPT_VERSION,
    SIN_EVIDENCIA,
    SIN_MODELO,
    PasajeParaRedactar,
    Redaccion,
    Validacion,
    faltantes_deterministas,
    oraciones,
    redactar,
    requiere_revision,
    validar,
)

__all__ = [
    "CITA_INEXISTENTE",
    "PROMPT_ID",
    "PROMPT_VERSION",
    "SIN_EVIDENCIA",
    "SIN_MODELO",
    "PasajeParaRedactar",
    "Redaccion",
    "Validacion",
    "faltantes_deterministas",
    "oraciones",
    "redactar",
    "requiere_revision",
    "validar",
]
