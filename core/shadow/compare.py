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
from core.shadow.types import Divergence, ShadowComparison, default_severity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.shadow.types import DeclaredItem, ExpectedItem

#: Diferencia relativa a partir de la cual el valor en aduana se considera
#: divergente. Por debajo suele ser redondeo o tipo de cambio de otro día, no
#: subvaluación — y acusar por un peso arruinaría la señal.
VALUE_TOLERANCE = Decimal("0.01")


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

    # ── Origen ───────────────────────────────────────────────────────────────
    if expected.country_of_origin and declared.country_of_origin != expected.country_of_origin:
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


def _lagunas(expected: ExpectedItem) -> list[str]:
    """Lo que no se pudo comprobar de esta partida, y por qué.

    Separado de `compare_item` porque no son hallazgos: son huecos. Una NOM que
    falta es una acusación contra el agente aduanal; no saber qué NOM aplica es
    una limitación nuestra, y mezclarlas dejaría al lector sin forma de
    distinguirlas (§36).
    """
    razones: list[str] = []
    if expected.required_nom_codes is None:
        razones.append(
            "no se conoce qué NOM exige la fracción "
            f"{expected.fraction_code or 'esperada'}: falta cargar la correlación "
            "fracción → NOM (Anexo 2.2.1 del Acuerdo de la SE)"
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
            divergencias.extend(
                x
                for x in compare_item(d, e)
                if x.kind not in (DivergenceType.FRACTION_MISMATCH, DivergenceType.NICO_MISMATCH)
            )
            no_verificables.extend(f"línea {d.line_number}: {r}" for r in _lagunas(e))
            continue

        divergencias.extend(compare_item(d, e))
        no_verificables.extend(f"línea {d.line_number}: {r}" for r in _lagunas(e))

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
