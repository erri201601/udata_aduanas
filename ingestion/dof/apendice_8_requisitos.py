"""Qué identificador del Apéndice 8 exige una clave de pedimento del
Apéndice 2 — Anexo 22, RGCE 2026 (DOF).

NO ES UN PARSER GENÉRICO, COMO `anexo22.py`

`docs/RECONOCIMIENTO_APENDICE_8.md` (6-oct) ya separó, de las 168 claves con
"Supuestos de Aplicación" cargado, cuáles remiten a una clave de documento
concreta del Apéndice 2 (categoría "a") frente a las que remiten a un
programa/decreto, a una fracción/NICO explícitos, o a prosa libre sin campo
posible. Ese reconocimiento listó 10 claves en la categoría estructurable:
`A3, AF, TD, V1, V4-V9`.

Verificando el texto real de `pedimento_identifiers.supuestos_de_aplicacion`
(no el resumen del reconocimiento) antes de escribir la migración, dos cosas
no eran como decía el reconocimiento:

- `TD` no es auto-referente: su texto dice «clave de documento K1», no
  «TD». Se corrige aquí.
- `AF` no nombra ninguna clave concreta («identificar el activo fijo,
  únicamente cuando la clave de documento no sea exclusiva para dicha
  mercancía») — es una condición de exclusión sobre cualquier clave, no un
  `identifier_code -> pedimento_key` de uno a uno. Queda fuera: inventar
  una clave que el documento no da estaría prohibido por §8.2 del maestro.

Por eso son 9 filas, no 10, y cada una se verificó a mano contra el texto ya
cargado (`SELECT supuestos_de_aplicacion FROM regulatory.pedimento_identifiers
WHERE code = '<clave>'`), igual que `ingestion/se/cuotas_compensatorias.py`
verifica cada resolución contra el documento primario.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Vigencia y fuente son las mismas constantes que ya usa
#: `ingestion.dof.load` para el resto del Anexo 22
#: (`ANEXO22_VALID_FROM`/`ANEXO22_SOURCE_URL`/`ANEXO22_SOURCE_DOCUMENT`) --
#: este módulo no las repite para no arriesgar que se desincronicen.


@dataclass(frozen=True)
class ParsedIdentifierRequirement:
    identifier_code: str
    pedimento_key: str
    scope_note: str | None


#: Verbatim de `pedimento_identifiers.supuestos_de_aplicacion`, verificado
#: por clave el 13-oct-2026 contra la fila ya cargada (PR #158 + carga del
#: 6-oct). `scope_note` es la cita de regla/artículo cuando el texto la
#: trae; `None` cuando sólo remite a la clave, sin más.
_REQUISITOS: tuple[ParsedIdentifierRequirement, ...] = (
    # "Identificar conforme a los supuestos de la clave de documento A3
    #  del apéndice 2."
    ParsedIdentifierRequirement("A3", "A3", None),
    # "Conforme a los supuestos de la clave de documento K1 del apéndice 2."
    # -- el reconocimiento del 6-oct citó "TD" aquí; el texto real dice K1.
    ParsedIdentifierRequirement("TD", "K1", None),
    # "Indicar conforme a los supuestos de la clave de documento V1 del
    #  apéndice 2 del presente Anexo, regla 4.3.21. y artículo 86 de la Ley."
    ParsedIdentifierRequirement("V1", "V1", "regla 4.3.21. y artículo 86 de la Ley"),
    # "Indicar conforme al supuesto de la clave de documento V4 del
    #  apéndice 2 del presente Anexo y la regla 4.3.13., fracción II."
    ParsedIdentifierRequirement("V4", "V4", "regla 4.3.13., fracción II"),
    # "Indicar conforme a los supuestos de la clave de documento V5 del
    #  apéndice 2 del presente Anexo y la regla 7.3.3., fracción XIII."
    ParsedIdentifierRequirement("V5", "V5", "regla 7.3.3., fracción XIII"),
    # "Indicar conforme al supuesto de la clave de documento V6 del
    #  apéndice 2 del presente Anexo y la regla 1.6.7."
    ParsedIdentifierRequirement("V6", "V6", "regla 1.6.7."),
    # "Indicar conforme al supuesto de la clave de documento V7, del
    #  apéndice 2 del presente Anexo y la regla 4.3.9."
    ParsedIdentifierRequirement("V7", "V7", "regla 4.3.9."),
    # "Indicar conforme al supuesto de la clave de documento V8 del
    #  apéndice 2 del presente Anexo y la regla 4.5.21., fracción II."
    ParsedIdentifierRequirement("V8", "V8", "regla 4.5.21., fracción II"),
    # "Indicar conforme al supuesto de la clave de documento V9 del
    #  apéndice 2 del presente Anexo y la regla 3.3.11."
    ParsedIdentifierRequirement("V9", "V9", "regla 3.3.11."),
)


def requisitos_apendice_8() -> list[ParsedIdentifierRequirement]:
    """Las 9 claves verificadas -- ver el módulo para por qué no son 10."""
    return list(_REQUISITOS)
