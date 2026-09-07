"""Tests del Product DNA Engine.

El más importante es `test_un_dato_ausente_produce_missing_no_un_valor_plausible`:
si el motor rellenara un dato que el documento no aporta, la invención viajaría
al RGI Engine, de ahí a una fracción arancelaria y de ahí a un pedimento,
indistinguible de un dato real.

Ninguno llama a un modelo. El extractor se inyecta, que es justo para lo que
existe el puerto.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.product_dna import (
    CATALOG,
    CRITICOS,
    ExtractedAttribute,
    ProductDnaDraft,
    SourceDocument,
    extract,
)

pytestmark = pytest.mark.unit


class ExtractorFalso:
    """Extractor determinista: devuelve lo que se le dé."""

    def __init__(self, *attrs: ExtractedAttribute, summary: str | None = None) -> None:
        self._draft = ProductDnaDraft(attributes=attrs, summary=summary)

    def extract(self, document: SourceDocument) -> ProductDnaDraft:
        return self._draft


DOC = SourceDocument(text="Laptop 14 pulgadas, 1.4 kg.", kind="datasheet")


def _extraer(*attrs: ExtractedAttribute) -> ProductDnaDraft:
    return extract(DOC, extractor=ExtractorFalso(*attrs))


# ── La regla que justifica el módulo ────────────────────────────────────────


def test_un_dato_ausente_produce_missing_no_un_valor_plausible() -> None:
    """EL TEST MÁS IMPORTANTE (backlog de Persona 1).

    El documento habla de una laptop y no menciona el voltaje. El motor no
    puede completar «220 V» porque sea lo habitual: un voltaje inventado
    cambiaría la fracción arancelaria.
    """
    dna = _extraer(
        ExtractedAttribute(name="weight", value="1.4", status="EXTRACTED", locator="p.2")
    )

    voltaje = dna.get("voltage")
    assert voltaje is not None
    assert voltaje.status == "MISSING"
    assert voltaje.value is None
    assert "voltage" in dna.missing_information


def test_un_valor_vacio_no_cuenta_como_dato() -> None:
    """Una cadena en blanco es ausencia disfrazada."""
    dna = _extraer(ExtractedAttribute(name="brand", value="   ", status="OBSERVED", locator="p.1"))

    marca = dna.get("brand")
    assert marca is not None
    assert marca.status == "MISSING"
    assert marca.value is None


# ── Saneamiento: el motor no confía en el extractor ─────────────────────────


def test_sin_localizacion_no_se_extrajo_del_documento() -> None:
    """Si nadie puede volver al documento y verlo, se dedujo."""
    dna = _extraer(
        ExtractedAttribute(
            name="materials", value="aluminio", status="OBSERVED", confidence=Decimal("0.8")
        )
    )

    materiales = dna.get("materials")
    assert materiales is not None
    assert materiales.status == "INFERRED"


def test_una_inferencia_sin_confianza_no_se_presenta_como_dato() -> None:
    """Sin confianza declarada, un dato deducido se lee igual que uno leído."""
    dna = _extraer(ExtractedAttribute(name="industry", value="cómputo", status="INFERRED"))

    industria = dna.get("industry")
    assert industria is not None
    assert industria.status == "MISSING"


def test_el_motor_nunca_sube_la_categoria_de_un_atributo() -> None:
    """Sanear sólo puede degradar. Nada entra valiendo más de lo que traía."""
    orden = {"OBSERVED": 0, "EXTRACTED": 1, "INFERRED": 2, "MISSING": 3}
    entrada = ExtractedAttribute(
        name="function",
        value="tratamiento de datos",
        status="INFERRED",
        confidence=Decimal("0.6"),
    )

    salida = _extraer(entrada).get("function")

    assert salida is not None
    assert orden[salida.status] >= orden[entrada.status]


# ── Catálogo cerrado ────────────────────────────────────────────────────────


def test_devuelve_siempre_el_catalogo_completo() -> None:
    """Un atributo que nadie buscó y uno que no está deben distinguirse."""
    dna = _extraer()

    assert tuple(a.name for a in dna.attributes) == CATALOG
    assert len(dna.attributes) == 18


def test_descarta_atributos_fuera_del_catalogo() -> None:
    """Un nombre inventado no tiene columna donde caer."""
    dna = _extraer(
        ExtractedAttribute(name="color_favorito", value="azul", status="OBSERVED", locator="p.1")
    )

    assert dna.get("color_favorito") is None
    assert len(dna.attributes) == 18


# ── missing_information ─────────────────────────────────────────────────────


def test_los_criticos_faltantes_van_primero() -> None:
    """Bloquean la clasificación; los demás sólo empobrecen la descripción."""
    dna = _extraer()
    primeros = dna.missing_information[: len(CRITICOS)]

    assert set(primeros) == CRITICOS


def test_lo_solido_no_aparece_como_faltante() -> None:
    dna = _extraer(
        ExtractedAttribute(name="weight", value="1.4", status="EXTRACTED", locator="p.2")
    )

    assert "weight" not in dna.missing_information
    assert dna.get("weight") in dna.solid()


# ── Integración con el resto del sistema ────────────────────────────────────


def test_lo_inferido_no_sostiene_una_clasificacion() -> None:
    """El RGI Engine pesa distinto un hecho observado y uno deducido."""
    dna = _extraer(
        ExtractedAttribute(
            name="materials", value="aluminio", status="INFERRED", confidence=Decimal("0.58")
        )
    )
    materiales = dna.get("materials")

    assert materiales is not None
    assert materiales.is_known
    assert not materiales.is_solid
    assert materiales not in dna.solid()


def test_los_atributos_encajan_en_product_fact_del_rgi() -> None:
    """El motor produce lo que el RGI consume, sin que se importen entre sí."""
    from core.rgi_engine.context import ProductFact

    dna = _extraer(
        ExtractedAttribute(name="function", value="cómputo", status="EXTRACTED", locator="p.1")
    )
    hecho = ProductFact(**dna.get("function").to_fact_fields())  # type: ignore[union-attr]

    assert hecho.name == "function"
    assert hecho.is_solid


def test_los_atributos_encajan_en_la_tabla_del_canonical_model() -> None:
    """`to_attribute_fields()` alimenta `intelligence.product_attributes`."""
    from database.models import ProductAttribute

    dna = _extraer(
        ExtractedAttribute(name="weight", value="1.4", status="EXTRACTED", locator="p.2")
    )
    fila = ProductAttribute(
        **dna.get("weight").to_attribute_fields(),  # type: ignore[union-attr]
        data_origin="SYNTHETIC",
    )

    assert fila.name == "weight"
    assert fila.unit == "kg"
    assert fila.status == "EXTRACTED"


def test_el_borrador_alimenta_la_tabla_product_dnas() -> None:
    dna = _extraer(
        summary_attr := ExtractedAttribute(
            name="brand", value="Demo", status="EXTRACTED", locator="p.1"
        )
    )
    campos = dna.to_dna_fields()

    assert summary_attr.name == "brand"
    assert set(campos) == {"summary", "missing_information", "input_kinds"}
    assert campos["input_kinds"] == ["datasheet"]
