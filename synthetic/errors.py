"""`ErrorInjector` (§24/§25 maestro): las 3 anomalías nuevas que `synthetic/`
sabe producir hoy -- `WRONG_IDENTIFIER`, `INCONSISTENT_SKU_CLASSIFICATION`,
`MISSING_INCREMENTABLE`.

Por qué sólo 3 de las 6 que pidió Persona 1, y no las otras tres:

- `MISSING_NOM`: ninguna de las 12 fichas de `synthetic/catalog.py` tiene
  una fracción con una fila SIN acotar en `regulatory.
  fraction_nom_requirements` (ADR 0003) -- verificado, cero filas para
  las 10 fracciones reales del catálogo. Afirmar que a un producto de este
  catálogo le falta una NOM sin esa fuente violaría §8.1 del maestro.
- `MISSED_PROSEC`/`MISSED_PREFERENCE`: `core/opportunity/engine.py` ya lo
  dice de frente -- esas tasas son datos jurídicos con vigencia y fuente,
  y PROSEC/Regla 8a/preferencias todavía no están cargadas (tarea 3,
  pendiente). No se puede afirmar que una operación "debió" usar un
  beneficio que no se puede sostener con una fuente real.

Las tres SÍ implementadas no dependen de ninguna fuente jurídica todavía
sin cargar:

- `WRONG_IDENTIFIER` se apoya en `regulatory.pedimento_identifier_
  requirements` (ADR 0012, ya cargada) -- un dato OFFICIAL real.
- `INCONSISTENT_SKU_CLASSIFICATION` y `MISSING_INCREMENTABLE` son
  consistencia interna del propio pedimento/factura, no requieren ninguna
  fuente externa.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from synthetic.catalog import PRODUCT_CATALOG

if TYPE_CHECKING:
    from decimal import Decimal

#: Códigos del corpus (ver `ingestion.sintetico.corpus_espejo.ANOMALY_MAP`,
#: que es la única traducción válida a `ERROR_TYPE` -- no se repite aquí.
IDENTIFICADOR_INCORRECTO = "IDENTIFICADOR_INCORRECTO"
SKU_CLASIFICADO_INCONSISTENTE = "SKU_CLASIFICADO_INCONSISTENTE"
INCREMENTABLE_FALTANTE = "INCREMENTABLE_FALTANTE"
NOM_FALTANTE = "NOM_FALTANTE"
PROSEC_NO_APROVECHADO = "PROSEC_NO_APROVECHADO"


@dataclass(frozen=True)
class AnomalySpec:
    """Lo que hace falta para escribir una fila de `anomalies` en el JSON
    (mismas 4 claves que `ingestion.sintetico.corpus_espejo._parse_anomaly`
    espera: `code`, `field`, `expected`, `observed`)."""

    code: str
    field: str
    expected: str
    observed: str

    def as_json(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field": self.field,
            "expected": self.expected,
            "observed": self.observed,
        }


def identificador_incorrecto(*, pedimento_key: str, identifier_code: str) -> AnomalySpec:
    """Omite el identificador que `pedimento_identifier_requirements`
    (ADR 0012) exige para esta `pedimento_key` -- p. ej. declarar clave de
    documento `V1` sin el identificador `V1` del Apéndice 8."""
    return AnomalySpec(
        code=IDENTIFICADOR_INCORRECTO,
        # El campo con el que el Espejo emite un identificador de pedimento
        # que falta (`CAMPO_IDENTIFICADORES_DEL_DOCUMENTO`, ADR 0012).
        field="document_identifiers",
        expected=f"{identifier_code} (exigido por pedimento_key={pedimento_key})",
        observed="",
    )


def sku_clasificado_inconsistente(*, sku: str, fraccion_anterior: str) -> AnomalySpec:
    """La partida declara una fracción distinta de la que el MISMO sku
    (otro pedimento) ya declaró -- ver `sku_history` en
    `core/shadow/compare.py`."""
    return AnomalySpec(
        code=SKU_CLASIFICADO_INCONSISTENTE,
        field="declared_fraction_code",
        expected=fraccion_anterior,
        observed=f"SKU {sku} reclasificado",
    )


def incrementable_faltante(*, correcto: Decimal, declarado: Decimal) -> AnomalySpec:
    """El importe de incrementables declarado omite un concepto real del
    art. 65 de la Ley Aduanera (flete, seguro, regalías, ensamble) que la
    propia operación trae -- `correcto` es lo que debería incluir."""
    return AnomalySpec(
        code=INCREMENTABLE_FALTANTE,
        field="incrementables_mxn",
        expected=str(correcto),
        observed=str(declarado),
    )


def fraccion_alternativa_misma_mercancia(product_id: str) -> str:
    """Una fracción real y distinta de la correcta, dentro del mismo grupo
    de la cuota compensatoria del cable de acero (ADR 0009) -- nunca una
    fracción de otro capítulo: la inconsistencia tiene que ser creíble
    (alguien pudo confundir el diámetro), no un error absurdo."""
    from synthetic.catalog import FRACCIONES_CUOTA_CABLE_ACERO

    correcta = PRODUCT_CATALOG[product_id].fraction_code
    alternativas = sorted(FRACCIONES_CUOTA_CABLE_ACERO - {correcta})
    return alternativas[0]


def nom_faltante(*, nom: str) -> AnomalySpec:
    """La fracción declarada exige `nom` (Anexo 2.4.1, sin acotación) y la
    partida no la declara."""
    return AnomalySpec(code=NOM_FALTANTE, field="applied_nom_codes", expected=nom, observed="")


def prosec_no_aprovechado(
    *, sector: str, tasa_general: Decimal, tasa_prosec: Decimal
) -> AnomalySpec:
    """El importador opera en un sector PROSEC cuya tasa para la fracción es
    menor, y pagó la general. Es una OPORTUNIDAD, no un error del pedimento:
    se detecta en `opportunity_findings`, no en `risk_findings`."""
    return AnomalySpec(
        code=PROSEC_NO_APROVECHADO,
        field="igi_rate",
        expected=f"{tasa_prosec} (PROSEC sector {sector})",
        observed=str(tasa_general),
    )
