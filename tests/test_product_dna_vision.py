"""Tests de la extracción desde imágenes.

El que importa es `test_lo_leido_de_una_imagen_nunca_queda_en_observed`: un
modelo que «ve» 220 V en una etiqueta borrosa no lo observó, lo dedujo de unos
píxeles, y el sistema no tiene forma de comprobar si acertó.

Ninguno llama a un modelo: el proveedor se simula, que es para lo que existe
el puerto.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from core.llm.errors import ProviderResponseError
from core.llm.types import CallMetadata, ModelResponse, Usage
from core.product_dna import (
    TOPE_DESDE_IMAGEN,
    ImagenNoSoportadaError,
    SourceDocument,
    VisionExtractor,
    extract,
)

pytestmark = pytest.mark.unit

IMAGEN = b"\xff\xd8\xff\xe0fake-jpeg"
DOC = SourceDocument(text="", kind="image", reference="etiqueta.jpg")


class ProveedorFalso:
    """Devuelve la respuesta que se le dé, sin llamar a nadie."""

    name = "falso"

    def __init__(self, respuesta: str) -> None:
        self._respuesta = respuesta
        self.recibido: dict[str, Any] = {}

    def analyze_image(
        self,
        image: bytes,
        prompt: str,
        *,
        media_type: str = "image/jpeg",
        model: str | None = None,
        max_tokens: int = 4096,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
    ) -> ModelResponse:
        self.recibido = {
            "bytes": len(image),
            "media_type": media_type,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "prompt": prompt,
        }
        return ModelResponse(
            text=self._respuesta,
            metadata=CallMetadata(
                model_provider="falso",
                model_name="vision-test",
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                usage=Usage(input_tokens=100, output_tokens=50),
                latency_ms=800,
                finish_reason="stop",
            ),
        )


def _respuesta(atributos: list[dict[str, Any]], summary: str = "Laptop en etiqueta.") -> str:
    return json.dumps({"summary": summary, "attributes": atributos})


def _extraer(atributos: list[dict[str, Any]]) -> Any:
    proveedor = ProveedorFalso(_respuesta(atributos))
    extractor = VisionExtractor(proveedor, image=IMAGEN)  # type: ignore[arg-type]
    return extract(DOC, extractor=extractor)


# ── La regla del módulo ─────────────────────────────────────────────────────


def test_lo_leido_de_una_imagen_nunca_queda_en_observed() -> None:
    """EL TEST QUE IMPORTA.

    `OBSERVED` significa «aparece literal y es directamente verificable». Una
    imagen no lo permite: no hay forma de comprobar la lectura contra el
    original.
    """
    dna = _extraer(
        [
            {
                "name": "voltage",
                "value": "220",
                "status": "OBSERVED",
                "confidence": "0.95",
                "evidence_reference": "placa de datos",
            }
        ]
    )
    voltaje = dna.get("voltage")

    assert voltaje is not None
    assert voltaje.status != "OBSERVED"
    assert voltaje.status == TOPE_DESDE_IMAGEN


def test_el_tope_degrada_pero_no_sube() -> None:
    """Un `INFERRED` no se convierte en `EXTRACTED` por venir de una imagen."""
    dna = _extraer(
        [
            {
                "name": "materials",
                "value": "aluminio",
                "status": "INFERRED",
                "confidence": "0.6",
            }
        ]
    )
    materiales = dna.get("materials")

    assert materiales is not None
    assert materiales.status == "INFERRED"


def test_un_dato_ausente_en_la_imagen_sigue_siendo_missing() -> None:
    """El saneamiento del motor se aplica igual que con texto."""
    dna = _extraer([])

    voltaje = dna.get("voltage")
    assert voltaje is not None
    assert voltaje.status == "MISSING"
    assert "voltage" in dna.missing_information


def test_sin_localizacion_baja_a_inferido() -> None:
    """Regla del motor: lo que no se puede localizar no se extrajo."""
    dna = _extraer([{"name": "brand", "value": "Demo", "status": "EXTRACTED", "confidence": "0.8"}])
    marca = dna.get("brand")

    assert marca is not None
    assert marca.status == "INFERRED"


# ── Trazabilidad ────────────────────────────────────────────────────────────


def test_la_llamada_declara_su_prompt() -> None:
    """Sin `prompt_version` no se puede construir evidencia de modelo (§49)."""
    proveedor = ProveedorFalso(_respuesta([]))
    extractor = VisionExtractor(proveedor, image=IMAGEN)  # type: ignore[arg-type]
    extract(DOC, extractor=extractor)

    assert proveedor.recibido["prompt_id"] == "product_dna.extract_image"
    assert proveedor.recibido["prompt_version"] == "0.1"
    assert extractor.last_metadata is not None
    assert extractor.last_metadata.prompt_version == "0.1"


def test_el_prompt_declara_el_tipo_de_documento() -> None:
    """Saber si es etiqueta o ficha cambia cuánto se puede confiar."""
    proveedor = ProveedorFalso(_respuesta([]))
    extractor = VisionExtractor(proveedor, image=IMAGEN)  # type: ignore[arg-type]
    extract(SourceDocument(text="", kind="datasheet"), extractor=extractor)

    assert "datasheet" in proveedor.recibido["prompt"]


# ── Errores explícitos ──────────────────────────────────────────────────────


def test_un_pdf_no_pasa_por_imagen() -> None:
    """Rasterizar es responsabilidad de quien llama, y hay que decirlo.

    Dejarlo pasar produciría un error del proveedor que nadie sabría leer.
    """
    with pytest.raises(ImagenNoSoportadaError, match="rasterizarlo"):
        VisionExtractor(ProveedorFalso(""), image=IMAGEN, media_type="application/pdf")  # type: ignore[arg-type]


def test_una_respuesta_sin_json_no_finge_un_borrador_vacio() -> None:
    """Un borrador vacío se confundiría con «la imagen no aportaba nada»."""
    extractor = VisionExtractor(ProveedorFalso("No puedo leer la imagen."), image=IMAGEN)  # type: ignore[arg-type]

    with pytest.raises(ProviderResponseError, match="no contiene JSON"):
        extract(DOC, extractor=extractor)


def test_json_envuelto_en_texto_se_recupera() -> None:
    """Los modelos suelen rodear el JSON de explicación o de un bloque."""
    envuelto = (
        "Claro, esto es lo que veo:\n```json\n"
        + _respuesta(
            [{"name": "brand", "value": "Demo", "status": "INFERRED", "confidence": "0.7"}]
        )
        + "\n```\nEspero que sirva."
    )
    extractor = VisionExtractor(ProveedorFalso(envuelto), image=IMAGEN)  # type: ignore[arg-type]
    dna = extract(DOC, extractor=extractor)

    assert dna.get("brand") is not None
    assert dna.get("brand").value == "Demo"  # type: ignore[union-attr]


def test_un_atributo_fuera_del_catalogo_se_descarta() -> None:
    dna = _extraer(
        [{"name": "color_de_la_caja", "value": "azul", "status": "INFERRED", "confidence": "0.5"}]
    )

    assert dna.get("color_de_la_caja") is None
    assert len(dna.attributes) == 18


def test_la_confianza_llega_como_decimal() -> None:
    """§22: nada de float donde importa la precisión."""
    dna = _extraer([{"name": "weight", "value": "1.4", "status": "INFERRED", "confidence": "0.58"}])
    peso = dna.get("weight")

    assert peso is not None
    assert isinstance(peso.confidence, Decimal)
    assert peso.confidence == Decimal("0.58")
