"""RAW -> PARSED del corpus espejo V1 (15 pedimentos sintéticos, §24/§26).

Fuente: `sintetico/corpus_espejo_v1_20260921.{pdf,json}` en MinIO (subidos por
Persona 1, `content_hash` verificado en destino). El JSON es la única verdad
de referencia; el PDF es el documento que un humano leería.

Este módulo sólo parsea — de `dict` (ya cargado con `json.loads`) a
dataclasses tipadas. No abre sesión de base, no decide `data_origin`, no
resuelve fracciones contra la tarifa: eso es `ingestion.sintetico.load`.

EL CONTRATO QUE EL CARGADOR NO PUEDE ROMPER

Cada partida trae DOS vistas del mismo conjunto de campos, `expected` y
`observed`. Sólo `observed` puede llegar a las tablas operativas — es el
dato "impreso" en el pedimento simulado. `expected` es la verdad de
referencia contra la que se mide, y vive únicamente en
`intelligence.ground_truth_records` vía `anomalies`. Mezclarlos deja al
motor ver la respuesta antes de responder.

`technical_spec`/`classification_evaluable` vienen POR PARTIDA, no por
producto: en las 21 partidas con `classification_evaluable=false` el spec
está recortado a propósito frente al de referencia en `product_specs`
(nivel superior del JSON) — la comparación contra esa referencia es lo que
permite reconstruir CUÁLES características faltan, sin adivinar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

#: (código de anomalía del corpus) -> (`ERROR_TYPE`, `expected_field` o None).
#: Los cuatro fiscales comparten `WRONG_VALUE` porque `expected_field` ya dice
#: qué campo está mal — un tipo por concepto habría duplicado esa columna
#: (mismo razonamiento que la migración 79d42f2e1bf2).
ANOMALY_MAP: dict[str, tuple[str, str | None]] = {
    "FRACCION_INCORRECTA": ("WRONG_FRACTION", None),
    "NICO_INCORRECTO": ("WRONG_NICO", None),
    "PAIS_ORIGEN_INCONSISTENTE": ("WRONG_ORIGIN", None),
    "UMC_INVALIDA": ("WRONG_UNIT", None),
    "CANTIDAD_UMC_INCONSISTENTE": ("INCONSISTENT_QUANTITY", None),
    "CAMPO_TECNICO_FALTANTE": ("MISSING_TECHNICAL_FIELD", None),
    "IGI_TASA_INCORRECTA": ("WRONG_VALUE", "igi_rate"),
    "IVA_BASE_INCORRECTA": ("WRONG_VALUE", "iva_base"),
    "IVA_IMPORTE_INCORRECTO": ("WRONG_VALUE", "iva_amount"),
    "VALOR_ADUANA_INCONSISTENTE": ("WRONG_VALUE", "customs_value"),
}

#: Las 6 anomalías de cantidad son INDETECTABLES a propósito (hallazgo de
#: Persona 1, 21-sep-2026): el precio unitario del PDF se calculó con la
#: cantidad ya alterada, así que no hay inconsistencia aritmética que las
#: delate. Marcarlo en la base evita que la métrica las compense con un
#: filtro escrito a mano.
ANOMALIAS_INDETECTABLES = frozenset({"CANTIDAD_UMC_INCONSISTENTE"})


def _d(valor: object) -> Decimal:
    return Decimal(str(valor))


@dataclass(frozen=True)
class ParsedAnomaly:
    code: str
    field: str
    expected_value: str
    observed_value: str

    @property
    def error_type_y_campo(self) -> tuple[str, str | None]:
        return ANOMALY_MAP[self.code]

    @property
    def expected_detection(self) -> bool:
        return self.code not in ANOMALIAS_INDETECTABLES


@dataclass(frozen=True)
class ParsedPartida:
    sec: str
    product_id: str
    commercial_description: str
    technical_spec: dict[str, Any]
    classification_evaluable: bool
    classification_reason: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    anomalies: list[ParsedAnomaly]

    @property
    def line_number(self) -> int:
        return int(self.sec)


@dataclass(frozen=True)
class ParsedPedimento:
    document_id: str
    is_simulation: bool
    pedimento_number: str
    operation: str  # "IMP"/"EXP" -> TRADE_FLOW ("IMPORT"/"EXPORT")
    pedimento_key: str
    regime: str
    exchange_rate: Decimal
    entry_customs: str
    date_entry: date
    date_payment: date
    importer_rfc: str
    importer_name: str
    importer_address: str
    provider_name: str
    provider_address: str
    provider_country: str
    provider_incoterm: str
    provider_currency: str
    totals_valor_aduana_mxn: Decimal
    parts: list[ParsedPartida]

    @property
    def trade_flow(self) -> str:
        return {"IMP": "IMPORT", "EXP": "EXPORT"}[self.operation]


@dataclass(frozen=True)
class ParsedProductSpec:
    """La ficha de CATÁLOGO de un producto (`product_specs` del JSON) — UNA
    por `product_id`, compartida por todas las partidas que lo declaran,
    en el mismo pedimento o en otro distinto (hallazgo de Persona 1,
    22-sep-2026: sin esto, `INCONSISTENT_SKU_CLASSIFICATION` no puede
    existir, porque necesita el MISMO producto comparado entre pedimentos)."""

    id: str
    name: str
    description: str
    #: La ficha técnica COMPLETA de catálogo. Sirve para saber QUÉ
    #: característica falta en las partidas con `classification_evaluable=false`
    #: — nunca para rellenar el spec recortado de una partida.
    spec: dict[str, Any]


@dataclass(frozen=True)
class ParsedCorpus:
    pedimentos: list[ParsedPedimento]
    #: `product_id` -> su ficha de catálogo.
    product_specs: dict[str, ParsedProductSpec]


def _parse_anomaly(raw: dict[str, Any]) -> ParsedAnomaly:
    return ParsedAnomaly(
        code=raw["code"],
        field=raw["field"],
        expected_value=str(raw["expected"]),
        observed_value=str(raw["observed"]),
    )


def _parse_partida(raw: dict[str, Any]) -> ParsedPartida:
    return ParsedPartida(
        sec=raw["sec"],
        product_id=raw["product_id"],
        commercial_description=raw["commercial_description"],
        technical_spec=dict(raw["technical_spec"]),
        classification_evaluable=raw["classification_evaluable"],
        classification_reason=raw["classification_reason"],
        expected=dict(raw["expected"]),
        observed=dict(raw["observed"]),
        anomalies=[_parse_anomaly(a) for a in raw["anomalies"]],
    )


def _parse_pedimento(raw: dict[str, Any]) -> ParsedPedimento:
    importador = raw["importer"]
    proveedor = raw["provider"]
    return ParsedPedimento(
        document_id=raw["document_id"],
        is_simulation=raw["is_simulation"],
        pedimento_number=raw["pedimento_number"],
        operation=raw["operation"],
        pedimento_key=raw["pedimento_key"],
        regime=raw["regime"],
        exchange_rate=_d(raw["exchange_rate"]),
        entry_customs=raw["entry_customs"],
        date_entry=date.fromisoformat(raw["date_entry"]),
        date_payment=date.fromisoformat(raw["date_payment"]),
        importer_rfc=importador["rfc"],
        importer_name=importador["name"],
        importer_address=importador["address"],
        provider_name=proveedor["name"],
        provider_address=proveedor["address"],
        provider_country=proveedor["country"],
        provider_incoterm=proveedor["incoterm"],
        provider_currency=proveedor["currency"],
        totals_valor_aduana_mxn=_d(raw["totals"]["valor_aduana_mxn"]),
        parts=[_parse_partida(p) for p in raw["parts"]],
    )


def parse_corpus(raw: dict[str, Any]) -> ParsedCorpus:
    """`ground_truth` + `product_specs` del JSON -> `ParsedCorpus`.

    Falla ruidoso (`KeyError`/`ValueError`) si al corpus le falta algo que
    se espera: un extractor que "se las arregla" con un JSON incompleto
    produce datos incorrectos en silencio (regla 7 CLAUDE.md).
    """
    pedimentos = [_parse_pedimento(doc) for _, doc in sorted(raw["ground_truth"].items())]
    product_specs = {
        pid: ParsedProductSpec(
            id=spec["id"],
            name=spec["name"],
            description=spec["description"],
            spec=dict(spec["spec"]),
        )
        for pid, spec in raw["product_specs"].items()
    }
    return ParsedCorpus(pedimentos=pedimentos, product_specs=product_specs)
