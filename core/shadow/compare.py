"""La comparación: lo declarado contra lo esperado.

REGLA QUE GOBIERNA TODO ESTE MÓDULO

Una divergencia sólo se emite cuando el sistema puede SOSTENER su expectativa.
Si la clasificación no llegó a ser defendible, o si el dato esperado no existe,
NO se acusa: se declara no verificable.

Es la diferencia entre «la fracción declarada está mal» y «no pude comprobar la
fracción declarada». La primera acusa a un agente aduanal de un error que
acarrea multa; la segunda pide que alguien lo mire. Emitir la primera sin
fundamento destruiría la confianza en el sistema mucho más rápido de lo que
cualquier acierto la construye.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from core.shadow.divergences import DivergenceType
from core.shadow.types import ORIGEN_DEL_PROVEEDOR, Divergence, ShadowComparison, default_severity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.shadow.types import DeclaredItem, ExpectedItem

#: Diferencia relativa a partir de la cual el valor en aduana se considera
#: divergente. Por debajo suele ser redondeo o tipo de cambio de otro día, no
#: subvaluación — y acusar por un peso arruinaría la señal.
VALUE_TOLERANCE = Decimal("0.01")

#: Tolerancia absoluta de las comprobaciones fiscales, en la moneda de la
#: partida. Dos céntimos: el pedimento redondea a centavos y nuestro cálculo
#: también, así que una diferencia menor es redondeo, no un hallazgo. Mismo
#: criterio que el validador de corpus de Persona 1.
TOLERANCIA_FISCAL = Decimal("0.02")


def compare_item(declared: DeclaredItem, expected: ExpectedItem) -> list[Divergence]:
    """Compara una partida. Devuelve las divergencias que se pueden sostener."""
    hallazgos: list[Divergence] = []

    def emitir(
        kind: DivergenceType,
        field: str,
        dec: str | None,
        exp: str | None,
        razon: str,
        severidad: str | None = None,
    ) -> None:
        hallazgos.append(
            Divergence(
                kind=kind,
                line_number=declared.line_number,
                field=field,
                declared_value=dec,
                expected_value=exp,
                severity=severidad or default_severity(kind),
                confidence=expected.confidence,
                reasoning=razon,
                source_ids=expected.source_ids,
            )
        )

    # ── Fracción ─────────────────────────────────────────────────────────────
    # Sólo si la clasificación se sostiene. Sin eso no hay contra qué comparar.
    if expected.is_resolved and expected.fraction_code:
        if not declared.fraction_code:
            emitir(
                DivergenceType.FRACTION_MISMATCH,
                "fraction_code",
                None,
                expected.fraction_code,
                "La partida no declara fracción arancelaria.",
            )
        elif declared.fraction_code != expected.fraction_code:
            emitir(
                DivergenceType.FRACTION_MISMATCH,
                "fraction_code",
                declared.fraction_code,
                expected.fraction_code,
                (
                    f"La mercancía corresponde a {expected.fraction_code} según las RGI, "
                    f"y se declaró {declared.fraction_code}. Cambia el arancel aplicable."
                ),
            )

    # ── NICO ─────────────────────────────────────────────────────────────────
    # Sólo tiene sentido si la fracción coincide: comparar el NICO de dos
    # fracciones distintas no dice nada útil, y duplicaría el hallazgo.
    misma_fraccion = (
        declared.fraction_code
        and expected.fraction_code
        and declared.fraction_code == expected.fraction_code
    )
    if misma_fraccion and expected.nico_code and declared.nico_code != expected.nico_code:
        emitir(
            DivergenceType.NICO_MISMATCH,
            "nico_code",
            declared.nico_code,
            expected.nico_code,
            f"El NICO esperado para {expected.fraction_code} es {expected.nico_code}.",
        )

    # Lo único que el catálogo puede afirmar solo: que el NICO declarado NO
    # existe en su fracción. No hace falta saber cuál es el correcto para saber
    # que éste no lo es.
    elif (
        expected.valid_nico_codes
        and declared.nico_code
        and declared.nico_code not in expected.valid_nico_codes
    ):
        vigentes = ", ".join(expected.valid_nico_codes) or "ninguno"
        emitir(
            DivergenceType.NICO_MISMATCH,
            "nico_code",
            declared.nico_code,
            None,
            (
                f"El NICO {declared.nico_code} no existe en la fracción "
                f"{declared.fraction_code}. Los vigentes son: {vigentes}."
            ),
        )

    # ── IGI ──────────────────────────────────────────────────────────────────
    # No necesita clasificar: la tasa se consulta para la fracción DECLARADA.
    # Aunque esa fracción estuviera equivocada, el importe tiene que cuadrar
    # con la tasa de la que se declaró — y si no cuadra, eso ya es un hallazgo
    # que no depende de saber cuál era la correcta.
    if (
        expected.igi_amount is not None
        and declared.igi_amount is not None
        and abs(declared.igi_amount - expected.igi_amount) > TOLERANCIA_FISCAL
    ):
        emitir(
            DivergenceType.IGI_RATE_MISMATCH,
            "igi_amount",
            str(declared.igi_amount),
            str(expected.igi_amount),
            (
                f"El IGI declarado no corresponde a la tarifa de la fracción "
                f"{declared.fraction_code}: sale {expected.igi_amount} y se declaró "
                f"{declared.igi_amount}."
            ),
        )

    # ── IVA ──────────────────────────────────────────────────────────────────
    # Una base alterada y un importe alterado se ven igual desde aquí: las dos
    # desvían el importe. No se afirma cuál de las dos fue.
    if (
        expected.vat_amount is not None
        and declared.vat_amount is not None
        and abs(declared.vat_amount - expected.vat_amount) > TOLERANCIA_FISCAL
    ):
        emitir(
            DivergenceType.VAT_MISMATCH,
            "vat_amount",
            str(declared.vat_amount),
            str(expected.vat_amount),
            (
                f"El IVA declarado no cuadra con su base —valor en aduana más IGI "
                f"más DTA—: sale {expected.vat_amount} y se declaró {declared.vat_amount}. "
                "Puede ser la base o el importe; desde el pedimento no se distingue."
            ),
        )

    # ── Unidad de medida ─────────────────────────────────────────────────────
    if expected.declared_unit_is_known is False and declared.unit:
        emitir(
            DivergenceType.UNIT_MISMATCH,
            "unit",
            declared.unit,
            None,
            (f"La unidad declarada {declared.unit} no existe en el Apéndice 7 del Anexo 22."),
        )

    # ── Ficha técnica incompleta ─────────────────────────────────────────────
    # No compara nada: mira si el expediente alcanza. Por eso no depende de que
    # la clasificación se sostenga — al contrario, suele ser la razón de que no
    # se sostenga.
    if expected.missing_technical_fields:
        campos = ", ".join(expected.missing_technical_fields)
        emitir(
            DivergenceType.MISSING_TECHNICAL_FIELD,
            "missing_information",
            None,
            campos,
            (
                f"La ficha técnica no trae {campos}. La clasificación declarada "
                "no se puede defender con el expediente actual: se le pide al "
                "proveedor, no se corrige el pedimento."
            ),
        )

    # ── Origen ───────────────────────────────────────────────────────────────
    if expected.country_of_origin and declared.country_of_origin != expected.country_of_origin:
        if expected.origin_source == ORIGEN_DEL_PROVEEDOR:
            # NO es una acusación: un pedimento con orígenes mixtos es legítimo.
            # Se emite para que una persona lo confirme, con el motivo escrito.
            emitir(
                DivergenceType.ORIGIN_MISMATCH,
                "country_of_origin",
                declared.country_of_origin,
                expected.country_of_origin,
                (
                    f"La partida declara origen {declared.country_of_origin or 'ninguno'} "
                    f"y el proveedor del documento es de {expected.country_of_origin}. "
                    "Un pedimento con orígenes mixtos es legítimo, así que esto NO "
                    "afirma que lo declarado esté mal: pide que una persona lo "
                    "confirme contra el certificado de origen."
                ),
                "MEDIUM",
            )
        else:
            emitir(
                DivergenceType.ORIGIN_MISMATCH,
                "country_of_origin",
                declared.country_of_origin,
                expected.country_of_origin,
                (
                    f"El producto es de origen {expected.country_of_origin} y se declaró "
                    f"{declared.country_of_origin or 'ninguno'}. Puede cambiar la "
                    f"preferencia arancelaria aplicable."
                ),
            )

    # ── NOM ──────────────────────────────────────────────────────────────────
    # `None` es «no sé qué NOM exige esta fracción», no «no exige ninguna».
    # Recorrer una tupla vacía en ese caso daría cero faltantes y el pedimento
    # se leería como limpio sin haberlo comprobado. La laguna se reporta en
    # `_lagunas()`, del lado de `unverifiable`.
    faltantes = [
        n for n in (expected.required_nom_codes or ()) if n not in declared.applied_nom_codes
    ]
    for nom in faltantes:
        emitir(
            DivergenceType.MISSING_NOM,
            "applied_nom_codes",
            ", ".join(declared.applied_nom_codes) or None,
            nom,
            f"La fracción exige {nom} y no se declaró. Puede detener la mercancía.",
        )

    # ── Identificadores del Anexo 22 ─────────────────────────────────────────
    for ident in expected.required_identifiers or ():
        if ident not in declared.identifiers:
            emitir(
                DivergenceType.IDENTIFIER_MISMATCH,
                "identifiers",
                ", ".join(sorted(declared.identifiers)) or None,
                ident,
                f"Falta el identificador {ident} que exige la operación.",
            )

    # ── Valor en aduana ──────────────────────────────────────────────────────
    if expected.customs_value is not None and declared.customs_value is not None:
        if declared.customs_value_currency != expected.customs_value_currency:
            # Comparar importes en divisas distintas daría una diferencia falsa
            # y enorme. Se reporta la discrepancia de divisa, no el monto.
            emitir(
                DivergenceType.VALUE_MISMATCH,
                "customs_value_currency",
                declared.customs_value_currency,
                expected.customs_value_currency,
                "El valor declarado está en otra divisa que la esperada.",
            )
        else:
            base = expected.customs_value
            diferencia = abs(declared.customs_value - base)
            relativa = diferencia / base if base else Decimal("0")
            if relativa > VALUE_TOLERANCE:
                emitir(
                    DivergenceType.VALUE_MISMATCH,
                    "customs_value",
                    str(declared.customs_value),
                    str(base),
                    (
                        f"Diferencia de {relativa:.1%} sobre el valor esperado. "
                        f"Por debajo del {VALUE_TOLERANCE:.0%} se considera redondeo."
                    ),
                )

    return hallazgos


def _depende_de_clasificar(divergencia: Divergence, expected: ExpectedItem) -> bool:
    """¿Este hallazgo se apoya en una clasificación que no se sostuvo?

    La fracción, siempre. El NICO, sólo cuando la expectativa dice CUÁL debería
    ser —eso sale de clasificar—. El otro hallazgo de NICO, «el declarado no
    existe en su fracción», sale del catálogo y de lo DECLARADO: no clasifica
    nada y por tanto no se cae con la clasificación (Persona 1, 21-sep).
    """
    if divergencia.kind is DivergenceType.FRACTION_MISMATCH:
        return True
    if divergencia.kind is DivergenceType.NICO_MISMATCH:
        return expected.nico_code is not None
    return False


def _lagunas(expected: ExpectedItem, declared: DeclaredItem | None = None) -> list[str]:
    """Lo que no se pudo comprobar de esta partida, y por qué.

    Separado de `compare_item` porque no son hallazgos: son huecos. Una NOM que
    falta es una acusación contra el agente aduanal; no saber qué NOM aplica es
    una limitación nuestra, y mezclarlas dejaría al lector sin forma de
    distinguirlas (§36).
    """
    razones: list[str] = []
    if expected.customs_value is None:
        razones.append(
            "no consta el precio pagado ni los incrementables de la partida, "
            "así que el valor en aduana declarado no se pudo contrastar"
        )
    if expected.nico_code is None and declared is not None and declared.nico_code:
        # Sólo cuando NO hay una expectativa firme de cuál es el NICO: ahí lo
        # único que se puede decir sale del catálogo, y no siempre alcanza.
        if expected.valid_nico_codes is None:
            razones.append(
                f"no se pudo comprobar el NICO {declared.nico_code}: la fracción declarada "
                "no está vigente en la tarifa, así que el catálogo no dice nada de ella"
            )
        elif not expected.valid_nico_codes:
            razones.append(
                f"no se pudo comprobar el NICO {declared.nico_code}: la fracción declarada "
                "no tiene NICO cargados, y eso es un hueco del catálogo, no del pedimento"
            )
        elif declared.nico_code in expected.valid_nico_codes:
            razones.append(
                f"el NICO {declared.nico_code} existe en la fracción declarada; saber si es "
                "el que corresponde a la mercancía exige la ficha técnica, que no está cargada"
            )

    if expected.igi_amount is None:
        razones.append(
            "no se pudo comprobar el IGI: falta la tasa de la fracción declarada en la "
            "tarifa vigente, o no se pasaron las tasas de la operación"
        )
    if expected.vat_amount is None:
        razones.append(
            "no se pudo comprobar el IVA: hace falta el IGI esperado y las tasas de IVA "
            "y DTA de la operación, que las pasa quien audita"
        )
    if expected.declared_unit_is_known is None and declared is not None and declared.unit:
        razones.append(
            f"no se pudo comprobar la unidad {declared.unit}: no se consultó el "
            "Apéndice 7 del Anexo 22"
        )
    if expected.country_of_origin is None:
        razones.append(
            "no consta el país del proveedor: la partida no está ligada a una factura, "
            "así que el origen declarado no se pudo contrastar con nada"
        )
    if expected.missing_technical_fields is None:
        razones.append(
            "no se consultó la ficha técnica: sin producto ligado o sin Product DNA "
            "no se puede decir si el expediente alcanza"
        )
    if expected.required_nom_codes is None:
        razones.append(
            "no se conoce qué NOM exige la fracción "
            f"{expected.fraction_code or 'esperada'}: falta cargar la correlación "
            "fracción → NOM (Anexo 2.4.1 del Acuerdo de la SE)"
        )
    if expected.required_identifiers is None:
        razones.append(
            "no se conocen los identificadores que exige la operación: "
            "falta cargar el Apéndice 8 del Anexo 22"
        )
    return razones


def compare(
    declared: Sequence[DeclaredItem],
    expected: Sequence[ExpectedItem],
    *,
    sku_history: dict[str, str] | None = None,
) -> ShadowComparison:
    """Compara un pedimento completo contra su espejo.

    `sku_history` mapea SKU a la fracción con la que se clasificó antes. Una
    inconsistencia ahí es un hallazgo aunque la clasificación de hoy sea
    correcta: significa que una de las dos operaciones está mal, y eso ya
    merece que alguien lo mire.
    """
    por_linea = {e.line_number: e for e in expected}
    divergencias: list[Divergence] = []
    no_verificables: list[str] = []

    for d in declared:
        e = por_linea.get(d.line_number)

        if e is None:
            no_verificables.append(
                f"línea {d.line_number}: no se construyó expectativa para esta partida"
            )
            continue

        if not e.is_resolved:
            # El sistema no pudo sostener una clasificación. Decir que lo
            # declarado está mal sería acusar sin fundamento.
            no_verificables.append(
                f"línea {d.line_number}: la clasificación no llegó a ser defendible, "
                f"no se puede afirmar que lo declarado sea incorrecto"
            )
            # Aun así se comparan los campos que NO dependen de clasificar:
            # el origen y las NOM ya declaradas siguen siendo comprobables.
            divergencias.extend(x for x in compare_item(d, e) if not _depende_de_clasificar(x, e))
            no_verificables.extend(f"línea {d.line_number}: {r}" for r in _lagunas(e, d))
            continue

        divergencias.extend(compare_item(d, e))
        no_verificables.extend(f"línea {d.line_number}: {r}" for r in _lagunas(e, d))

    # ── Consistencia histórica del SKU ───────────────────────────────────────
    if sku_history:
        for d in declared:
            if not d.sku or not d.fraction_code:
                continue
            anterior = sku_history.get(d.sku)
            if anterior and anterior != d.fraction_code:
                divergencias.append(
                    Divergence(
                        kind=DivergenceType.INCONSISTENT_SKU_CLASSIFICATION,
                        line_number=d.line_number,
                        field="fraction_code",
                        declared_value=d.fraction_code,
                        expected_value=anterior,
                        severity=default_severity(DivergenceType.INCONSISTENT_SKU_CLASSIFICATION),
                        reasoning=(
                            f"El SKU {d.sku} se clasificó antes como {anterior} y ahora "
                            f"como {d.fraction_code}. No se afirma cuál es la correcta: "
                            f"una de las dos operaciones tiene un error."
                        ),
                    )
                )

    return ShadowComparison(divergences=tuple(divergencias), unverifiable=tuple(no_verificables))
