"""Tests unitarios de `synthetic/` (§24/§25 maestro): deterministas, sin
tocar ninguna base de datos -- usan una tasa de cambio fija inyectada."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from ingestion.sintetico.corpus_espejo import parse_corpus
from synthetic.catalog import PRODUCT_CATALOG
from synthetic.corpus import construir_corpus_nuevo

pytestmark = pytest.mark.unit


def _tasa_fija(_fecha: date) -> Decimal:
    return Decimal("17.00")


def test_es_reproducible_por_construccion() -> None:
    """No hay azar: dos llamadas producen el mismo dict, campo por campo."""
    raw1 = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    raw2 = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)

    assert raw1 == raw2


def test_parsea_sin_romper_el_contrato_existente() -> None:
    """El cargador ya revisado (`ingestion.sintetico.corpus_espejo.
    parse_corpus`) tiene que poder leer esto sin cambios -- es la condición
    para montarse encima de él en vez de duplicarlo."""
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)

    corpus = parse_corpus(raw)

    assert len(corpus.pedimentos) == 5
    assert {p.id for p in corpus.product_specs.values()} == set(PRODUCT_CATALOG)


def test_no_declara_ningun_producto_fuera_del_catalogo_de_12() -> None:
    """Condición de Persona 1: la carga nueva no puede crear fichas nuevas,
    o se pierden los veredictos ya firmados sobre las 12 existentes."""
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)

    ids_usados = {parte.product_id for ped in corpus.pedimentos for parte in ped.parts}

    assert ids_usados <= set(PRODUCT_CATALOG)


def test_usa_la_tasa_de_cambio_inyectada_no_un_valor_fijo_inventado() -> None:
    """Lo que esta tarea vino a cerrar: nada de 18.33 repetido."""
    tasas_vistas: list[Decimal] = []

    def tasa_espia(fecha: date) -> Decimal:
        tasa = Decimal("17.00") + Decimal(fecha.day) / Decimal("100")
        tasas_vistas.append(tasa)
        return tasa

    raw = construir_corpus_nuevo(tasa_de_cambio=tasa_espia)

    tasas_en_json = {Decimal(str(p["exchange_rate"])) for p in raw["ground_truth"].values()}
    assert tasas_en_json == set(tasas_vistas)
    assert Decimal("18.33") not in tasas_en_json


def test_wrong_identifier_declara_v1_sin_el_identificador() -> None:
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)
    ped = next(p for p in corpus.pedimentos if p.document_id == "PED_SIM_016")

    assert ped.pedimento_key == "V1"
    # V1 es de nivel G: el identificador se declara en el pedimento (ADR 0012).
    assert ped.identifiers == {}
    (parte,) = ped.parts
    assert "identifiers" not in parte.observed
    (anomalia,) = parte.anomalies
    assert anomalia.code == "IDENTIFICADOR_INCORRECTO"
    assert anomalia.expected_detection is True


def test_inconsistent_sku_el_mismo_sku_dos_fracciones_distintas() -> None:
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)
    limpio = next(p for p in corpus.pedimentos if p.document_id == "PED_SIM_017")
    inconsistente = next(p for p in corpus.pedimentos if p.document_id == "PED_SIM_018")

    sku_limpio = limpio.parts[0].observed["sku_override"]
    sku_malo = inconsistente.parts[0].observed["sku_override"]
    assert sku_limpio == sku_malo

    assert limpio.parts[0].observed["fraccion"] != inconsistente.parts[0].observed["fraccion"]
    # Las dos declaraciones son de pedimentos (y por lo tanto clientes)
    # DISTINTOS -- condición real para no chocar con
    # `uq_products_client_id_sku`.
    assert limpio.importer_rfc != inconsistente.importer_rfc

    (anomalia,) = inconsistente.parts[0].anomalies
    assert anomalia.code == "SKU_CLASIFICADO_INCONSISTENTE"


def test_missing_incrementable_lo_esperado_es_mayor_que_lo_declarado() -> None:
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)
    ped = next(p for p in corpus.pedimentos if p.document_id == "PED_SIM_019")
    (parte,) = ped.parts

    declarado = Decimal(str(parte.observed["incrementables_mxn"]))
    correcto = Decimal(str(parte.expected["incrementables_mxn"]))
    assert correcto > declarado
    # `valor_aduana_mxn` tiene que ser consistente con SU PROPIO
    # incrementables en cada vista -- nunca mezclado.
    assert (
        Decimal(str(parte.observed["valor_aduana_mxn"]))
        == Decimal(str(parte.observed["precio_pagado_mxn"])) + declarado
    )


def test_rectificacion_apunta_al_original_y_corrige_el_identificador() -> None:
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)
    original = next(p for p in corpus.pedimentos if p.document_id == "PED_SIM_016")
    rectificacion = next(p for p in corpus.pedimentos if p.document_id == "PED_SIM_020")

    assert rectificacion.rectifies_pedimento_number == original.pedimento_number
    assert rectificacion.rectification_number == 1
    assert rectificacion.parts[0].anomalies == []
    assert "V1" in rectificacion.identifiers


def test_las_partidas_de_cable_traen_peso_neto() -> None:
    raw = construir_corpus_nuevo(tasa_de_cambio=_tasa_fija)
    corpus = parse_corpus(raw)

    for ped in corpus.pedimentos:
        for parte in ped.parts:
            if parte.product_id in {"P005", "P006", "P007"}:
                assert parte.observed.get("net_weight_kg") is not None
                assert parte.observed["net_weight_kg"] > 0
