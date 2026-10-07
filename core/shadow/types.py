"""Los dos lados de la comparación, y el resultado.

La idea entera del Pedimento Espejo (§9.3) es que el sistema construya lo que
DEBERÍA declararse sin mirar lo declarado, y sólo después compare. Si mirara
primero, tendería a justificar lo que ya está ahí — que es exactamente el sesgo
que un revisor humano tiene y que la máquina debería no tener.

Por eso `ExpectedItem` se construye desde el Product DNA y la clasificación, y
`DeclaredItem` desde el pedimento, sin que ninguno conozca al otro.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from core.shadow.divergences import DEFAULT_SEVERITY, DivergenceType


class DeclaredItem(BaseModel):
    """Una partida tal como viene en el pedimento.

    Todo es opcional salvo la línea: un pedimento incompleto es justamente uno
    de los hallazgos posibles, así que el tipo tiene que poder representarlo.
    """

    model_config = ConfigDict(frozen=True)

    line_number: int
    description: str | None = None
    fraction_code: str | None = None
    nico_code: str | None = None
    country_of_origin: str | None = None
    customs_value: Decimal | None = None
    customs_value_currency: str | None = None
    applied_nom_codes: tuple[str, ...] = ()
    identifiers: dict[str, Any] = Field(default_factory=dict)
    sku: str | None = None

    unit: str | None = None
    """Unidad de medida comercial declarada (clave del Apéndice 7, Anexo 22)."""
    igi_amount: Decimal | None = None
    vat_amount: Decimal | None = None
    exchange_rate: Decimal | None = None
    """Tipo de cambio declarado en el PEDIMENTO (no en la partida) — se
    repite igual en cada línea, mismo patrón que las tasas de DTA/IVA que
    llegan por `ReviewRequest`: es un dato del documento completo, no de
    esta partida en particular."""
    cc_amount: Decimal | None = None
    """Cuota compensatoria declarada en la partida. `None` = no consta —
    el pedimento real puede simplemente no declararla."""


#: `ExpectedItem.origin_source` cuando el país esperado se dedujo del proveedor
#: del documento y no de una fuente firme como el certificado de origen.
ORIGEN_DEL_PROVEEDOR: Final = "SUPPLIER"


class ExpectedItem(BaseModel):
    """Lo que el sistema esperaría ver, construido sin mirar lo declarado."""

    model_config = ConfigDict(frozen=True)

    line_number: int
    fraction_code: str | None = None
    nico_code: str | None = None
    fraction_source: str | None = None
    """Quién sostiene la fracción esperada. `None` = el motor, por las RGI.

    Con texto —«el dictamen de César del 2026-10-07»— la sostiene un
    clasificador, y el hallazgo tiene que decirlo: no es lo mismo «según las
    RGI» que «según el criterio firmado de una persona». Las dos acusan con
    fundamento; quien lea el hallazgo tiene que saber cuál.
    """
    nico_source: str | None = None
    """Quién sostiene el NICO esperado. `None` = el catálogo o el motor.

    Con texto, un clasificador lo firmó en su dictamen. Igual que con la
    fracción, el hallazgo lo dice.
    """
    country_of_origin: str | None = None
    origin_source: str | None = None
    """De dónde sale el país esperado. `None` = de una fuente firme.

    `ORIGEN_DEL_PROVEEDOR` significa que se dedujo del proveedor del documento,
    y eso cambia cómo se presenta la divergencia: un pedimento con orígenes
    mixtos es LEGÍTIMO en la vida real —una fábrica en China puede enviar
    piezas fabricadas en Brasil—, así que declarar un origen distinto al del
    proveedor no es un error, es algo que una persona tiene que confirmar
    contra el certificado de origen. Tratarlo como error duro llenaría de
    falsos positivos en cuanto lleguen pedimentos reales (Persona 1, 21-sep).
    """
    customs_value: Decimal | None = None
    customs_value_currency: str | None = None
    igi_amount: Decimal | None = None
    """IGI que sale de aplicar la tarifa a la fracción DECLARADA.

    Se calcula sin clasificar: aunque la fracción estuviera mal, el importe
    tiene que cuadrar con la tasa de la que se declaró. `None` = no se pudo
    consultar la tasa, y entonces no se compara.
    """

    vat_amount: Decimal | None = None
    """IVA que sale de su base: valor en aduana + IGI + DTA.

    Las tasas las pasa quien llama; el motor no las inventa (§8.1).
    """

    exchange_rate: Decimal | None = None
    """El FIX vigente para la fecha de operación y la divisa de la factura.

    `None` cuando el pedimento no tiene divisa distinta de MXN que convertir
    (nada que comparar), o cuando no hay tasa FIX cargada para esa fecha —
    las dos son «no se pudo comprobar», nunca «coincide».

    La fecha exacta que debería aplicar (operación, pago, u otra) no está
    verificada contra una fuente almacenada — ver el docstring de
    `DivergenceType.EXCHANGE_RATE_MISMATCH`.
    """

    compensatory_duty_applies: bool | None = None
    """¿Esta partida (origen + fracción, a la fecha de operación) tiene una
    cuota compensatoria conocida? `None` = no se sabe (default: sólo una
    combinación está verificada hoy, ver
    `ingestion.se.cuotas_compensatorias`). `True` = sí, hay una fila
    vigente en `regulatory.CompensatoryDuty`. NUNCA `False`: no se ha
    verificado lo suficiente para afirmar que una combinación no tiene
    cuota — eso exigiría conocer TODAS las resoluciones reales, no sólo
    una."""

    compensatory_duty_amount: Decimal | None = None
    """El importe esperado (`rate * cantidad`), sólo cuando la unidad
    declarada de la partida coincide con la de la cuota. `None` aunque
    `compensatory_duty_applies` sea `True` cuando no coincide (p. ej. la
    cuota es "por kilogramo" y la partida declara en metro lineal) — no se
    inventa un factor de conversión; el hallazgo se emite igual, sin monto
    numérico (ver `DivergenceType.COMPENSATORY_DUTY_MISMATCH`)."""

    declared_unit_is_known: bool | None = None
    """¿La unidad declarada existe en el Apéndice 7? `None` = no se consultó."""

    valid_nico_codes: tuple[str, ...] | None = None
    """Los NICO que existen en la fracción DECLARADA. `None` = no se consultó.

    Sirve para lo único que el catálogo puede decir por sí solo: si el NICO
    declarado existe o no. Que exista NO significa que sea el correcto para la
    mercancía —eso exige la ficha técnica— y por eso son dos cosas separadas:
    la primera es un hallazgo, la segunda un hueco declarado (Persona 1,
    21-sep).
    """

    required_nom_codes: tuple[str, ...] | None = None
    """Las NOM que la fracción exige. `None` significa QUE NO SE SABE.

    La distinción no es cosmética. Una tupla vacía afirma «esta fracción no
    exige ninguna NOM» y permite decir que el pedimento está limpio en ese
    campo; `None` dice «no tengo la fuente para saberlo» y manda la partida a
    `unverifiable`.

    El valor por omisión es `None` a propósito: hoy no existe la correlación
    fracción → NOM. No está en el Anexo 22 (verificado por Persona 2 el
    2026-09-08: el Apéndice 9 explica qué significa cada código, pero remite al
    Anexo 2.4.1 de un Acuerdo distinto de la Secretaría de Economía para saber
    qué fracciones lo exigen). Mientras esa fuente no esté cargada, quien
    construya un `ExpectedItem` sin tocar este campo obtiene «no sé», que es la
    verdad, en vez de «no exige ninguna», que sería inventar.
    """

    missing_technical_fields: tuple[str, ...] | None = None
    """Qué le falta a la ficha técnica, según el propio extractor.

    Tres valores distintos, y la diferencia importa:
    `None`   no se consultó la ficha —no hay producto ligado o no hay DNA—, y
             entonces la partida no está limpia: está sin mirar.
    `()`     la ficha está completa. Eso sí permite decir que no hay hueco.
    con algo lo que falta, tal como lo declaró el extractor.

    No se inventa aquí una lista de campos obligatorios: el motor no sabe qué
    exige cada mercancía, y suponerlo llenaría de hallazgos falsos.
    """

    required_identifiers: tuple[str, ...] | None = None
    """Identificadores del Anexo 22 que la operación exige. `None` = no se sabe.

    Misma semántica que `required_nom_codes`. El Apéndice 8 del Anexo 22 —el
    catálogo de identificadores— está pendiente de cargar.
    """
    sku: str | None = None

    confidence: Decimal | None = None
    """Cuánta confianza tiene el sistema en lo que espera.

    Importa para no acusar con seguridad desde una base insegura: una
    divergencia contra una expectativa de confianza 0.4 no es un hallazgo, es
    una pregunta.
    """

    source_ids: tuple[Any, ...] = ()
    is_resolved: bool = False
    """`False` cuando la clasificación no llegó a ser defendible. Entonces no
    se puede afirmar que lo declarado esté mal: sólo que no se pudo verificar.
    """


class Divergence(BaseModel):
    """Una diferencia concreta entre lo declarado y lo esperado."""

    model_config = ConfigDict(frozen=True)

    kind: DivergenceType
    line_number: int
    field: str
    declared_value: str | None = None
    expected_value: str | None = None
    severity: str = "MEDIUM"
    confidence: Decimal | None = None
    reasoning: str = ""
    source_ids: tuple[Any, ...] = ()
    requires_human_review: bool = True

    def to_finding_fields(self) -> dict[str, Any]:
        """Mapeo plano hacia `intelligence.risk_findings`.

        `core/` no importa la persistencia (§29): quien escriba la fila
        ensambla, igual que en los otros motores.
        """
        return {
            "finding_type": self.kind.value,
            "field": self.field,
            "declared_value": self.declared_value,
            "expected_value": self.expected_value,
            "severity": self.severity,
            "confidence": self.confidence,
            "requires_human_review": self.requires_human_review,
            "reasoning": self.reasoning,
        }


class ShadowComparison(BaseModel):
    """El resultado de comparar un pedimento completo contra su espejo."""

    model_config = ConfigDict(frozen=True)

    divergences: tuple[Divergence, ...] = ()
    unverifiable: tuple[str, ...] = ()
    """Partidas que NO se pudieron verificar, con su razón.

    Se declaran aparte de las divergencias a propósito. «No encontré nada mal»
    y «no pude comprobarlo» son cosas distintas, y confundirlas haría que un
    pedimento sin verificar pareciera limpio (§36).
    """

    verified: tuple[str, ...] = ()
    """Qué SÍ se pudo comprobar de cada partida, con su nombre.

    Simétrico a `unverifiable`, y tan necesario como él. Sin esta mitad, la
    única forma de leer una partida con huecos era «sin verificar», y eso hacía
    parecer que el sistema no comprobaba nada en partidas donde comprobaba
    ocho de diez cosas.

    Decir lo que se comprobó no afloja la regla del §36: una partida no está
    limpia por tener ocho comprobaciones buenas si le faltan dos. Sólo permite
    distinguirla de otra donde no se pudo hacer ninguna.
    """

    @property
    def has_findings(self) -> bool:
        return bool(self.divergences)

    @property
    def is_complete(self) -> bool:
        """¿Se pudo verificar todo?

        Un `True` aquí es lo que permite decir «este pedimento está limpio».
        Con `False`, lo más que se puede decir es «no encontré nada en lo que
        pude revisar».
        """
        return not self.unverifiable

    def by_severity(self, severity: str) -> tuple[Divergence, ...]:
        return tuple(d for d in self.divergences if d.severity == severity)

    @property
    def worst_severity(self) -> str | None:
        """La severidad más alta encontrada. Ordena la bandeja de revisión."""
        orden = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        presentes = {d.severity for d in self.divergences}
        return next((s for s in orden if s in presentes), None)

    def summary(self) -> str:
        """Resumen legible, para que un humano lo lea o un LLM lo narre."""
        if not self.divergences and self.is_complete:
            return "Sin divergencias. Se verificaron todas las partidas."
        if not self.divergences:
            return (
                f"Sin divergencias en lo verificable, pero {len(self.unverifiable)} "
                f"partida(s) no se pudieron comprobar: {'; '.join(self.unverifiable)}"
            )
        lineas = [f"{len(self.divergences)} divergencia(s), la más grave {self.worst_severity}:"]
        lineas += [
            f"  [{d.severity}] línea {d.line_number} · {d.field}: "
            f"declarado {d.declared_value!r} vs esperado {d.expected_value!r}"
            for d in self.divergences
        ]
        if self.unverifiable:
            lineas.append("No verificable: " + "; ".join(self.unverifiable))
        return "\n".join(lineas)


def default_severity(kind: DivergenceType) -> str:
    """Severidad por defecto del tipo de divergencia."""
    return DEFAULT_SEVERITY.get(kind, "MEDIUM")
