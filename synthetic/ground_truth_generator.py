"""`GroundTruthGenerator` (§24/§26 maestro): empaqueta lo que `ErrorInjector`
decidió en la lista `anomalies` que espera el JSON del corpus -- la misma
forma que ya consume `ingestion.sintetico.corpus_espejo.parse_corpus`
(cada entrada: `code`, `field`, `expected`, `observed`).

Separado de `ErrorInjector` a propósito: el inyector decide QUÉ mutar y con
qué valor (conocimiento del dominio -- qué hace creíble una inconsistencia
de SKU, qué formula da el importe correcto); este módulo sólo decide si la
anomalía es `expected_detection=True` o `False` y arma la lista final. Es
la misma frontera que ya existe en `ingestion.sintetico.corpus_espejo`
(`ANOMALY_MAP` vs `ANOMALIAS_INDETECTABLES`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic.errors import AnomalySpec

#: Ninguna de las 3 anomalías nuevas es indetectable POR DISEÑO (al
#: contrario que `CANTIDAD_UMC_INCONSISTENTE`, donde el propio PDF se
#: calculó ya con el dato alterado). Si hoy no se detectan es porque falta
#: el cableado (`sku_history` nunca se pasa a `review_pedimento`,
#: `MISSING_INCREMENTABLE` no tiene detector) -- un hueco de
#: implementación, no una imposibilidad. `expected_detection=True` en las
#: tres deja ese hueco medible en vez de escondido (§39 maestro).
SIEMPRE_DETECTABLES = True


def construir_anomalies(especificaciones: list[AnomalySpec]) -> list[dict[str, str]]:
    """La lista `anomalies` del JSON para una partida, en el mismo orden
    en que se recibieron las especificaciones."""
    return [spec.as_json() for spec in especificaciones]
