"""El motor de auditoría: divergencias + dinero + evidencia = hallazgos.

    Pedimento Espejo  →  Money Finder  →  Evidence  →  Finding
       qué difiere       cuánto cuesta    con qué      accionable

Es lo que convierte «la fracción está mal» en «la fracción está mal y son
11,600 pesos omitidos, según la LIGIE vigente ese día». La primera frase se
ignora; la segunda se corrige.

CUÁNDO NO SE CUANTIFICA

Sólo las divergencias que cambian lo que se paga tienen impacto económico. Una
NOM faltante detiene la mercancía pero no altera las contribuciones, y un
identificador ausente tampoco. Inventarles un monto para que la tabla se vea
completa sería exactamente lo que el §36 prohíbe: un número plausible es peor
que un hueco declarado, porque el hueco se ve y el número no.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from core.audit.findings import AuditReport, Finding
from core.audit.severity import adjust
from core.shadow import DivergenceType
from core.taxation import compute_divergence, compute_taxes

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from core.evidence import Evidence
    from core.shadow import Divergence, ShadowComparison
    from core.taxation import DivergenceImpact, Money, TaxRates

#: Divergencias cuyo monto es el delta ENTERO de la partida.
#:
#: FRACTION y VALUE cambian la base o la tasa. ORIGIN puede cambiar la
#: preferencia arancelaria y con ella el arancel. Las tres explican LA MISMA
#: diferencia de contribuciones, y por eso cada una la lleva completa y los
#: totales no las suman entre sí.
CUANTIFICABLES: frozenset[DivergenceType] = frozenset(
    {
        DivergenceType.FRACTION_MISMATCH,
        DivergenceType.VALUE_MISMATCH,
        DivergenceType.ORIGIN_MISMATCH,
    }
)

#: Divergencias cuyo monto es el error de cálculo de UNA contribución.
#:
#: LA DIFERENCIA CON LAS DE ARRIBA, QUE ES LA DECISIÓN DE FONDO
#:
#: Estas dos no comparan tasas: comparan lo que el importador ESCRIBIÓ contra
#: lo que la ley da para la fracción que él mismo declaró. Un pedimento del
#: corpus trae IGI declarado 4 822.95 donde el Anexo da 14 468.85: **9 645.90
#: pesos omitidos**, y hasta hoy salían en la consola como «sin monto».
#:
#: No hace falta clasificar para afirmarlo —la tasa es la de la fracción
#: declarada— y es exacto. Comprobado contra las seis mutaciones sembradas de
#: `igi_rate` del corpus: el delta del hallazgo coincide al céntimo con
#: `(tasa original - tasa mutada) × valor en aduana` en las seis.
#:
#: Y NO SE SUMAN CON EL DELTA DE LA FRACCIÓN. ESTO SE INTENTÓ Y ESTABA MAL
#:
#: Parecía que las dos piezas telescopaban:
#:
#:     error de cálculo  = valor × tasa_declarada - IGI_declarado
#:     movimiento de tasa= valor × tasa_correcta  - valor × tasa_declarada
#:     ─────────────────────────────────────────────────────────────
#:     suma              = valor × tasa_correcta  - IGI_declarado
#:
#: Y telescopan, pero SÓLO contribución por contribución. El delta de la
#: fracción no mide una contribución: mide el movimiento de TODAS a la vez, y
#: lo mide desde los importes RECALCULADOS, no desde los escritos.
#:
#: El caso que lo destapó —un test, antes de que esto se mergeara—: valor
#: 100 000, tasa declarada 0.05, correcta 0.15, IGI escrito 1 000 e IVA escrito
#: 18 528. La suma daba 15 600 y lo que se debe son 13 872, porque el delta de
#: la fracción ya trae dentro el arrastre del IVA (16 800 a 18 400) medido
#: contra un IVA recalculado que nadie escribió, y el IVA escrito estaba 128
#: por encima.
#:
#: Sumar las dos sobre-acusa en cuanto una contribución no tiene su propio
#: hallazgo. Así que no se suman: una partida con error de cálculo reporta el
#: error de cálculo, que es exacto y no necesita clasificar, y la fracción
#: queda dicha aparte como lo que puede mover todavía más.
#:
#: Se reporta de menos a propósito. «Tu IGI está mal calculado por 9 645.90, y
#: además tu fracción podría estar mal» se sostiene delante de una autoridad;
#: un número mayor que mezcla dos bases no.
POR_CONTRIBUCION: frozenset[DivergenceType] = frozenset(
    {
        DivergenceType.IGI_RATE_MISMATCH,
        DivergenceType.VAT_MISMATCH,
    }
)

#: Cómo se agrega el monto de un hallazgo. Viaja con él a la base.
ALCANCE_LINEA = "LINEA_COMPLETA"
ALCANCE_CONTRIBUCION = "UNA_CONTRIBUCION"


def audit(
    comparison: ShadowComparison,
    *,
    transaction_value: Money | None = None,
    declared_rates: TaxRates | None = None,
    expected_rates: TaxRates | None = None,
    incrementables: Sequence[Money] = (),
    evidences: Sequence[Evidence] = (),
    is_simulation: bool = True,
) -> AuditReport:
    """Convierte una comparación del Espejo en hallazgos accionables.

    Sin `transaction_value` ni tasas, los hallazgos salen sin impacto: siguen
    siendo válidos como riesgo de cumplimiento, sólo que no cuantificados. Es
    un resultado honesto, no un fallo — y `is_actionable` lo distingue.
    """
    impacto = None
    supuestos: list[str] = []

    puede_cuantificar = (
        transaction_value is not None and declared_rates is not None and expected_rates is not None
    )

    if puede_cuantificar:
        declarado = compute_taxes(
            transaction_value=transaction_value,  # type: ignore[arg-type]
            rates=declared_rates,  # type: ignore[arg-type]
            incrementables=incrementables,
            is_simulation=is_simulation,
        )
        esperado = compute_taxes(
            transaction_value=transaction_value,  # type: ignore[arg-type]
            rates=expected_rates,  # type: ignore[arg-type]
            incrementables=incrementables,
            is_simulation=is_simulation,
        )
        impacto = compute_divergence(declared=declarado, expected=esperado)
        supuestos = list(esperado.assumptions)
    else:
        supuestos.append(
            "Sin tasas ni valor de transacción: los hallazgos van sin impacto "
            "económico. Son válidos como riesgo de cumplimiento, no cuantificados."
        )

    # El monto de una CAUSA se atribuye ENTERO, no se reparte. Repartirlo daría
    # cifras que no cuadran con nada verificable: la diferencia de
    # contribuciones que provoca una fracción mal es UNA, y cada causa la
    # explica por completo. `total_por_partida` se encarga de no contarla dos
    # veces.
    #
    # El de un error de cálculo es otra cosa y lo pone `_a_hallazgo` por su
    # cuenta: no necesita `impacto`, porque sale de los dos importes que el
    # propio hallazgo trae.
    divisa = transaction_value.currency if transaction_value is not None else None
    hallazgos = [
        _a_hallazgo(
            d,
            impacto=impacto if (impacto and d.kind in CUANTIFICABLES) else None,
            evidences=evidences,
            supuestos=supuestos,
            is_simulation=is_simulation,
            divisa_de_la_partida=divisa,
        )
        for d in comparison.divergences
    ]

    total_omitido = _total_de(hallazgos, "OMISION")
    total_recuperable = _total_de(hallazgos, "SOBREPAGO")

    return AuditReport(
        findings=tuple(hallazgos),
        unverifiable=comparison.unverifiable,
        verified=comparison.verified,
        total_exposure=total_omitido,
        total_recoverable=total_recuperable,
        currency=impacto.difference.currency if impacto else None,
        is_simulation=is_simulation or (impacto.is_simulation if impacto else True),
    )


def _error_de_calculo(divergencia: Divergence) -> Decimal | None:
    """Lo que falta de ESTA contribución, de los dos números del hallazgo.

    `expected_value` es lo que da la ley para la fracción que el importador
    declaró —`_espejo_documental` la calcula sin clasificar— y
    `declared_value` es lo que escribió. La diferencia es el dinero, exacta y
    sin intermediarios: no la produce el motor fiscal ni hace falta una
    expectativa de fracción que el motor pueda sostener.

    `None` cuando cualquiera de los dos no es un importe. No se fuerza: un
    campo que no es dinero no tiene delta, y convertirlo a cero lo presentaría
    como «comprobado y sin diferencia».
    """
    try:
        declarado = Decimal(divergencia.declared_value or "")
        esperado = Decimal(divergencia.expected_value or "")
    except (InvalidOperation, TypeError):
        return None
    return esperado - declarado


def _a_hallazgo(
    divergencia: Divergence,
    *,
    impacto: DivergenceImpact | None,
    evidences: Sequence[Evidence],
    supuestos: Sequence[str],
    is_simulation: bool,
    divisa_de_la_partida: str | None = None,
) -> Finding:
    """Convierte una divergencia en hallazgo, con su impacto si lo tiene."""
    monto: Decimal | None = None
    divisa: str | None = None
    direccion: str | None = None
    alcance: str | None = None

    if divergencia.kind in POR_CONTRIBUCION:
        # Este monto NO sale del motor fiscal: sale de los dos importes que el
        # hallazgo ya trae. Por eso existe aunque no haya tasas esperadas, que
        # es el caso de 3 de cada 4 partidas del corpus.
        monto = _error_de_calculo(divergencia)
        if monto is not None:
            divisa = divisa_de_la_partida
            direccion = "OMISION" if monto > 0 else "SOBREPAGO" if monto < 0 else "SIN_DIFERENCIA"
            alcance = ALCANCE_CONTRIBUCION
    elif impacto is not None:
        monto = impacto.difference.amount
        divisa = impacto.difference.currency
        direccion = impacto.direction
        alcance = ALCANCE_LINEA

    severidad, motivo = adjust(divergencia.severity, amount=monto)

    return Finding(
        divergence=divergencia,
        severity=severidad,
        severity_reason=motivo,
        impact_amount=monto,
        impact_currency=divisa,
        impact_direction=direccion,
        impact_scope=alcance,
        evidences=tuple(evidences),
        assumptions=tuple(supuestos),
        is_simulation=is_simulation,
    )


def _total_de(hallazgos: Sequence[Finding], direccion: str) -> Decimal | None:
    """Los hallazgos de una dirección, agregados con el criterio de siempre."""
    return total_por_partida(
        (f.impact_amount, f.impact_scope)
        for f in hallazgos
        if f.impact_direction == direccion and f.impact_amount is not None
    )


def total_por_partida(montos: Iterable[tuple[Decimal, str | None]]) -> Decimal | None:
    """El dinero de UNA partida en UNA dirección. La única función que agrega.

    Recibe pares `(importe, alcance)` y no hallazgos, a propósito: el Espejo y
    el tablero agregan filas de `risk_findings`, que no guardan la dirección
    —se deduce del signo— y fabricar un `Finding` falso para poder llamar aquí
    sería inventar un objeto para satisfacer una firma.

    LAS DOS CLASES DE MONTO SE AGREGAN AL CONTRARIO

    Una fracción equivocada y un valor equivocado producen **un único** delta y
    cada una lo lleva entero, así que sumarlos contaría el mismo dinero dos
    veces: de ésos se toma uno (`LINEA_COMPLETA`).

    Un IGI mal calculado y un IVA mal calculado son **contribuciones
    distintas** y se deben las dos: ésos se suman (`UNA_CONTRIBUCION`).
    Deduplicarlos se quedaría con el mayor y perdería el otro.

    Y LAS DOS CLASES NO SE SUMAN ENTRE SÍ

    Se intentó y estaba mal: el delta de la fracción mide el movimiento de
    todas las contribuciones a la vez y lo mide desde importes recalculados,
    así que sumarlo al error de cálculo sobre-acusa. La cuenta está arriba, en
    `POR_CONTRIBUCION`.

    Cuando una partida tiene error de cálculo, ése es su total: es exacto y no
    necesita clasificar. El delta de la fracción sólo manda cuando no hay
    error de cálculo que medir. Reportar de menos es el lado correcto del
    error aquí: un importe que mezcla dos bases no se sostiene delante de una
    autoridad.

    Las filas sin alcance —anteriores a la columna— se tratan como
    `LINEA_COMPLETA`: era el único tipo que llevaba monto.
    """
    de_la_linea: set[Decimal] = set()
    por_contribucion: list[Decimal] = []
    for importe, alcance in montos:
        if alcance == ALCANCE_CONTRIBUCION:
            por_contribucion.append(importe)
        else:
            de_la_linea.add(importe)

    if por_contribucion:
        return sum(por_contribucion, Decimal(0))
    if de_la_linea:
        return max(de_la_linea, key=abs)
    return None
