"""Validación de salida estructurada (regla 3 de TAREA_P3).

`generate_structured()` nunca devuelve JSON sin validar. Este módulo aísla las
dos piezas frágiles —extraer el JSON de la respuesta y validarlo contra el
esquema— para poder probarlas sin tocar la red.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

# Los modelos envuelven el JSON en ```json ... ``` con frecuencia, aunque se les
# pida lo contrario. Reintentar por eso sería tirar dinero.
_FENCE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL)


def extract_json(text: str) -> str:
    """Devuelve el fragmento JSON de una respuesta, tolerando envoltorios.

    Acepta el JSON pelado, dentro de una valla de código, o precedido de prosa.
    No valida: solo recorta. Si no encuentra nada plausible devuelve el texto
    original para que el error de validación sea el que informe.
    """
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group("body").strip()

    stripped = text.strip()
    for opening, closing in (("{", "}"), ("[", "]")):
        start = stripped.find(opening)
        end = stripped.rfind(closing)
        if start != -1 and end > start:
            return stripped[start : end + 1]
    return stripped


def validate_payload[T: BaseModel](raw: str, schema: type[T]) -> T:
    """Valida una respuesta cruda contra `schema`.

    Lanza `ValidationError` (Pydantic) tanto si el JSON está malformado como si
    no encaja con el esquema: al llamador solo le importa que no sirve.
    """
    payload = extract_json(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise _as_validation_error(schema, f"JSON malformado: {exc}") from exc
    return schema.model_validate(data)


def _as_validation_error[T: BaseModel](schema: type[T], message: str) -> ValidationError:
    """Envuelve un fallo de parseo como `ValidationError` del esquema."""
    return ValidationError.from_exception_data(
        schema.__name__,
        [{"type": "value_error", "loc": (), "input": message, "ctx": {"error": message}}],
    )


def repair_prompt(schema: type[BaseModel], error: str, previous: str) -> str:
    """Mensaje de corrección para el reintento.

    Devolver el error de validación al modelo es lo que hace que el segundo
    intento funcione; repetir el prompt original no cambia nada.
    """
    return (
        "Tu respuesta anterior no validó contra el esquema requerido.\n\n"
        f"Respuesta anterior:\n{previous}\n\n"
        f"Error de validación:\n{error}\n\n"
        "Esquema JSON esperado:\n"
        f"{json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)}\n\n"
        "Devuelve únicamente el JSON corregido, sin explicación ni valla de código."
    )


def schema_instruction(schema: type[BaseModel]) -> str:
    """Instrucción de formato que se añade al system prompt."""
    return (
        "Responde únicamente con un objeto JSON válido que cumpla este esquema. "
        "Sin prosa, sin valla de código.\n"
        f"{json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)}"
    )


def first_text(candidates: Sequence[str]) -> str:
    """Primer fragmento no vacío de una lista de textos; cadena vacía si no hay."""
    return next((c for c in candidates if c), "")
