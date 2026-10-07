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

    EXCHANGE_RATE_MISMATCH = "EXCHANGE_RATE_MISMATCH"
    """El tipo de cambio declarado en el pedimento no es el FIX vigente.

    Cambia el valor en aduana convertido a MXN, y con él el IGI y el IVA —
    mismo tipo de consecuencia que `VALUE_MISMATCH`. La fecha de publicación
    que corresponde a la fecha de operación es, por ahora,
    `NEEDS_VALIDATION`: no hay una fuente almacenada (Ley Aduanera/CFF) que
    diga si aplica la del día de la operación, la del día anterior al pago,
    o alguna otra regla — se usa `operation_date` por continuidad con
    `_valor_esperado` (Persona 2, 6-oct-2026), no porque esté verificado.
    """

    COMPENSATORY_DUTY_MISMATCH = "COMPENSATORY_DUTY_MISMATCH"
    """La partida es de un origen/fracción con cuota compensatoria conocida
    (`regulatory.CompensatoryDuty`, ADR 0009) y no la declaró, o el importe
    declarado no cuadra con `rate * cantidad`.

    SE EMITE AUNQUE NO SE PUEDA CALCULAR EL MONTO EXACTO: cuando la unidad
    declarada de la partida no es la de la cuota (p. ej. la resolución fija
    la tasa "por kilogramo" y la partida declara en metro lineal — caso
    real, cable de acero), no se inventa un factor de conversión; el
    hallazgo se emite igual ("falta declarar"), pero sin `expected_value`
    numérico — el texto lo explica.

    Sólo existe UNA combinación origen+fracción verificada hoy (cable de
    acero de China, ver `ingestion.se.cuotas_compensatorias`); para
    cualquier otra, `ExpectedItem.compensatory_duty_applies` es `None`
    ("no se sabe"), nunca `False` ("se sabe que no aplica") — no se ha
    verificado lo suficiente para afirmar lo segundo de ninguna
    combinación todavía.
    """

    IGI_RATE_MISMATCH = "IGI_RATE_MISMATCH"
    """El IGI declarado no es el que sale de aplicar la tarifa a esa fracción.

    Se comprueba SIN clasificar: la tasa se consulta para la fracción DECLARADA
    y a la fecha de la operación. Aunque la fracción estuviera equivocada, el
    importe tiene que cuadrar con la tasa de la que se declaró.
    """

    VAT_MISMATCH = "VAT_MISMATCH"
    """El IVA declarado no cuadra con su base.

    Base = valor en aduana + IGI + DTA, con las tasas que pasa quien llama. Una
    base alterada y un importe alterado se ven igual desde aquí —las dos
    desvían el importe— y el corpus las distingue por su ground truth, no el
    motor.
    """

    UNIT_MISMATCH = "UNIT_MISMATCH"
    """La unidad de medida declarada no existe en el Apéndice 7 del Anexo 22."""

    MISSING_TECHNICAL_FIELD = "MISSING_TECHNICAL_FIELD"
    """La ficha técnica no trae un dato que la clasificación necesita.

    NO ACUSA DE NADA A QUIEN DECLARÓ. Dice que el expediente, hoy, no alcanza
    para sostener lo declarado: si mañana llega una auditoría, no hay con qué
    defender la fracción. Se arregla pidiéndole al proveedor la ficha completa,
    no corrigiendo el pedimento.

    Sale de `ProductDna.missing_information`, que es lo que el extractor
    declara que le faltó — no una lista de campos obligatorios inventada aquí.
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
    # Cambia el valor en aduana convertido, igual que una subvaluación.
    DivergenceType.EXCHANGE_RATE_MISMATCH: "CRITICAL",
    # Cambia lo que se paga, igual que una fracción o un IGI equivocados.
    DivergenceType.COMPENSATORY_DUTY_MISMATCH: "CRITICAL",
    # Detiene la mercancía en el punto de entrada.
    DivergenceType.MISSING_NOM: "HIGH",
    # Puede cambiar la preferencia arancelaria.
    DivergenceType.ORIGIN_MISMATCH: "HIGH",
    # Cambia lo que se paga, igual que una fracción equivocada.
    DivergenceType.IGI_RATE_MISMATCH: "CRITICAL",
    # El importe del IVA sale de una base que no cuadra: es dinero, aunque el
    # error pueda estar en la base y no en la tasa.
    DivergenceType.VAT_MISMATCH: "HIGH",
    # No cambia el arancel pero sí la estadística y el cumplimiento.
    DivergenceType.NICO_MISMATCH: "MEDIUM",
    DivergenceType.UNIT_MISMATCH: "MEDIUM",
    DivergenceType.IDENTIFIER_MISMATCH: "MEDIUM",
    # Deja la clasificación sin respaldo, pero no afirma que esté mal ni cuesta
    # dinero por sí sola. MEDIUM a propósito: inflarla sería cobrar por un
    # hueco del expediente el precio de un error probado.
    DivergenceType.MISSING_TECHNICAL_FIELD: "MEDIUM",
    # Señala un problema sin decir de qué lado está.
    DivergenceType.INCONSISTENT_SKU_CLASSIFICATION: "MEDIUM",
}
