"""Qué identificador del Apéndice 8 exige una clave de pedimento del Apéndice 2
— Anexo 22, RGCE 2026 (DOF). Contrato: ADR 0012.

DE DÓNDE SALEN LAS 9 FILAS

`docs/RECONOCIMIENTO_APENDICE_8.md` (6-oct) separó 10 claves cuyo «Supuesto de
aplicación» remite a una clave de documento concreta: `A3, AF, TD, V1, V4-V9`.
Al leer el texto (Persona 2, 13-oct; verificado de nuevo contra el PDF crudo
de MinIO por Persona 1, 19-oct) dos no eran como decía el reconocimiento:

- `TD` no es auto-referente: remite a la clave de documento `K1`.
- `AF` no nombra ninguna clave («únicamente cuando la clave de documento no sea
  exclusiva para dicha mercancía»): es una condición de exclusión, no una
  regla clave → identificador. Queda fuera; inventarle una clave sería
  inventar fundamento (§8.1).

Las 10 son de nivel `G` (se declaran en el pedimento) según el propio
Apéndice 8 cargado en `regulatory.pedimento_identifiers`.

NO SE CONFÍA EN ESTA LISTA: SE COMPRUEBA CONTRA EL RAW

`verificar_contra_el_documento` busca, en el texto del PDF crudo, la fila de
cada identificador y la frase «clave de documento <X>». Una regla cuya frase no
aparezca no se carga y se reporta como `NEEDS_VALIDATION`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class ParsedIdentifierRequirement:
    identifier_code: str
    pedimento_key: str
    supuesto: str
    """El «Supuesto de aplicación» íntegro, tal como lo escribe el Apéndice 8."""
    identifier_level: str = "G"


_REQUISITOS: tuple[ParsedIdentifierRequirement, ...] = (
    ParsedIdentifierRequirement(
        "A3",
        "A3",
        "Identificar conforme a los supuestos de la clave de documento A3 del apéndice 2.",
    ),
    ParsedIdentifierRequirement(
        "TD", "K1", "Conforme a los supuestos de la clave de documento K1 del apéndice 2."
    ),
    ParsedIdentifierRequirement(
        "V1",
        "V1",
        "Indicar conforme a los supuestos de la clave de documento V1 del apéndice 2 del "
        "presente Anexo, regla 4.3.21. y artículo 86 de la Ley.",
    ),
    ParsedIdentifierRequirement(
        "V4",
        "V4",
        "Indicar conforme al supuesto de la clave de documento V4 del apéndice 2 del presente "
        "Anexo y la regla 4.3.13., fracción II.",
    ),
    ParsedIdentifierRequirement(
        "V5",
        "V5",
        "Indicar conforme a los supuestos de la clave de documento V5 del apéndice 2 del "
        "presente Anexo y la regla 7.3.3., fracción XIII.",
    ),
    ParsedIdentifierRequirement(
        "V6",
        "V6",
        "Indicar conforme al supuesto de la clave de documento V6 del apéndice 2 del presente "
        "Anexo y la regla 1.6.7.",
    ),
    ParsedIdentifierRequirement(
        "V7",
        "V7",
        "Indicar conforme al supuesto de la clave de documento V7, del apéndice 2 del presente "
        "Anexo y la regla 4.3.9.",
    ),
    ParsedIdentifierRequirement(
        "V8",
        "V8",
        "Indicar conforme al supuesto de la clave de documento V8 del apéndice 2 del presente "
        "Anexo y la regla 4.5.21., fracción II.",
    ),
    ParsedIdentifierRequirement(
        "V9",
        "V9",
        "Indicar conforme al supuesto de la clave de documento V9 del apéndice 2 del presente "
        "Anexo y la regla 3.3.11.",
    ),
)

#: Cuántas líneas del texto `-layout` se miran tras la fila del identificador.
#: El supuesto ocupa 3-4 líneas, pero un salto de página puede meter blancos.
_VENTANA = 16

#: El inicio de la fila de otro identificador: dos caracteres y un guion.
_OTRA_FILA = re.compile(r"^\s*[A-Z0-9]{2}\s*[-–]\s")


def requisitos_apendice_8() -> list[ParsedIdentifierRequirement]:
    """Las 9 reglas verificadas. Ver el módulo para por qué no son 10."""
    return list(_REQUISITOS)


def verificar_contra_el_documento(
    lineas: Sequence[str], requisitos: Sequence[ParsedIdentifierRequirement]
) -> tuple[list[ParsedIdentifierRequirement], list[str]]:
    """Separa las reglas que el texto del documento sostiene de las que no.

    `lineas` es el texto `-layout` del Anexo 22. Se busca la fila del
    Apéndice 8 —el código seguido de guion y la letra de nivel— y, en las
    líneas siguientes, la frase «clave de documento <X>» con espacios
    normalizados. Devuelve `(verificadas, motivos de las que no)`.
    """
    verificadas: list[ParsedIdentifierRequirement] = []
    fallidas: list[str] = []
    for req in requisitos:
        fila = re.compile(rf"^\s*{req.identifier_code}\s*[-–]\s.*\s{req.identifier_level}\s")
        # El texto `-layout` intercala la columna vecina («Declarar la clave
        # que corresponda…») dentro de la frase cuando ésta parte de línea:
        # se admiten hasta 12 palabras entre «clave de» y «documento <X>».
        frase = re.compile(rf"clave\s+de\s+(?:\S+\s+){{0,12}}?documento\s+{req.pedimento_key}\b")
        encontrada = False
        for i, linea in enumerate(lineas):
            if not fila.match(linea):
                continue
            # La ventana acaba en la fila del identificador siguiente: si no,
            # la frase de la regla de al lado validaría una regla falsa
            # («A3 exige K1» pasaba con la fila de TD dentro de la ventana).
            fin = i + 1
            while fin < min(len(lineas), i + _VENTANA) and not _OTRA_FILA.match(lineas[fin]):
                fin += 1
            bloque = " ".join(lineas[i:fin])
            if frase.search(re.sub(r"\s+", " ", bloque)):
                encontrada = True
                break
        if encontrada:
            verificadas.append(req)
        else:
            fallidas.append(
                f"{req.identifier_code} → {req.pedimento_key}: la frase «clave de documento "
                f"{req.pedimento_key}» no aparece en su fila del documento (NEEDS_VALIDATION)"
            )
    return verificadas, fallidas
