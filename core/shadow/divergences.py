"""Vocabulario de divergencias entre lo declarado y lo esperado.

Los siete tipos son los del §18 de la especificación de Persona 1. Cada uno
lleva su severidad por defecto, que no es una opinión: refleja la consecuencia
real de esa divergencia para el importador.

Una fracción equivocada cambia el arancel y puede acarrear multa y crédito
fiscal — CRITICAL. Una descripción que no coincide del todo con la ficha es
INFO: molesta, no cuesta dinero.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class DivergenceType(StrEnum):
    """Qué difiere entre el pedimento declarado y el esperado."""

    FRACTION_MISMATCH = "FRACTION_MISMATCH"
    """La fracción declarada no es la que corresponde a la mercancía."""

    NICO_MISMATCH = "NICO_MISMATCH"
    """El NICO no corresponde a la fracción declarada."""

    ORIGIN_MISMATCH = "ORIGIN_MISMATCH"
    """El país de origen declarado no coincide con el del producto.

    Puede cambiar la preferencia arancelaria aplicable y, con ella, el arancel.
    """

    MISSING_NOM = "MISSING_NOM"
    """La fracción exige una NOM que no se declaró.

    Es de las que detienen la mercancía en el punto de entrada.
    """

    IDENTIFIER_MISMATCH = "IDENTIFIER_MISMATCH"
    """Falta un identificador del Anexo 22 o está mal."""

    VALUE_MISMATCH = "VALUE_MISMATCH"
    """El valor en aduana declarado difiere del calculado.

    Subvaluar es de las infracciones más perseguidas.
    """

    INCONSISTENT_SKU_CLASSIFICATION = "INCONSISTENT_SKU_CLASSIFICATION"
    """El mismo SKU se clasificó distinto en operaciones anteriores.

    No dice cuál es la correcta: dice que una de las dos no lo es, y eso ya es
    un hallazgo. Es de los más valiosos porque sale del historial, no de la
    norma.
    """


#: Severidad por defecto de cada tipo (§21).
#:
#: Es un punto de partida, no la última palabra: el Audit Engine puede subirla
#: o bajarla según el monto y el contexto. Una fracción equivocada de mil pesos
#: y una de un millón no son el mismo hallazgo.
DEFAULT_SEVERITY: Final[dict[DivergenceType, str]] = {
    # Cambia el arancel. Multa, crédito fiscal y posible embargo.
    DivergenceType.FRACTION_MISMATCH: "CRITICAL",
    # Subvaluación: de las infracciones más perseguidas.
    DivergenceType.VALUE_MISMATCH: "CRITICAL",
    # Detiene la mercancía en el punto de entrada.
    DivergenceType.MISSING_NOM: "HIGH",
    # Puede cambiar la preferencia arancelaria.
    DivergenceType.ORIGIN_MISMATCH: "HIGH",
    # No cambia el arancel pero sí la estadística y el cumplimiento.
    DivergenceType.NICO_MISMATCH: "MEDIUM",
    DivergenceType.IDENTIFIER_MISMATCH: "MEDIUM",
    # Señala un problema sin decir de qué lado está.
    DivergenceType.INCONSISTENT_SKU_CLASSIFICATION: "MEDIUM",
}
