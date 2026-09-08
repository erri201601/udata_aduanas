"""Extracción de Product DNA desde imágenes (§16).

Fichas técnicas escaneadas, etiquetas y fotos de producto. Es una
implementación del puerto `Extractor`, igual que `LlmExtractor`: el
saneamiento de `engine.py` se aplica después, venga la extracción de texto o
de una imagen.

LO QUE SE LEE DE UNA FOTO NO SE OBSERVÓ

Un modelo que «ve» 220 V en una etiqueta borrosa no lo observó: lo dedujo de
unos píxeles. Una fotocopia mala, un ángulo torcido o un reflejo convierten
cualquier lectura en interpretación, y el sistema no tiene forma de comprobar
si acertó.

Por eso ningún atributo que salga de una imagen puede quedar en `OBSERVED`:
ese estado significa «aparece literal y es directamente verificable», y una
imagen no lo permite. El tope es `EXTRACTED`, y sólo cuando el modelo declara
haber leído texto nítido con su localización; todo lo demás baja a `INFERRED`.

El tope se degrada, nunca se sube. Si el día de mañana hay un OCR que entregue
confianza por carácter, será momento de revisar `TOPE_DESDE_IMAGEN` — con
datos, no por comodidad.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from core.llm.errors import ProviderResponseError
from core.product_dna.attributes import CATALOG, AttributeStatus
from core.product_dna.types import ExtractedAttribute, ProductDnaDraft
from core.prompts import load_prompt

if TYPE_CHECKING:
    from core.llm.base import ModelProvider
    from core.llm.types import CallMetadata
    from core.product_dna.types import SourceDocument

PROMPT_ID = "product_dna.extract_image"
PROMPT_VERSION = "0.1"

#: Lo máximo que puede valer un atributo leído de una imagen. `OBSERVED` queda
#: fuera: no hay forma de verificar la lectura contra el original.
TOPE_DESDE_IMAGEN: Final[AttributeStatus] = "EXTRACTED"

#: Orden de cercanía al documento. Se usa para topar, nunca para subir.
_ORDEN: Final[dict[str, int]] = {
    "OBSERVED": 0,
    "EXTRACTED": 1,
    "INFERRED": 2,
    "MISSING": 3,
}

#: Tipos que un proveedor de visión acepta. Un PDF no es una imagen: hay que
#: rasterizarlo antes, y hacerlo en silencio produciría un error del proveedor
#: que nadie sabría interpretar.
MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)


class ImagenNoSoportadaError(ValueError):
    """El formato recibido no lo acepta el proveedor de visión."""


def _topar(status: str) -> AttributeStatus:
    """Nunca por encima del tope. Sanear sólo degrada."""
    if status not in _ORDEN:
        return "MISSING"
    if _ORDEN[status] < _ORDEN[TOPE_DESDE_IMAGEN]:
        return TOPE_DESDE_IMAGEN
    return status  # type: ignore[return-value]


class VisionExtractor:
    """Extrae Product DNA de una imagen con `analyze_image()`.

    `last_metadata` guarda la trazabilidad de la última llamada para que quien
    orqueste construya la evidencia sin repetirla, igual que `LlmExtractor`.
    """

    def __init__(
        self,
        provider: ModelProvider,
        *,
        image: bytes,
        media_type: str = "image/jpeg",
    ) -> None:
        if media_type not in MEDIA_TYPES:
            raise ImagenNoSoportadaError(
                f"{media_type} no es una imagen que el proveedor acepte; "
                f"admitidos: {', '.join(sorted(MEDIA_TYPES))}. "
                "Un PDF hay que rasterizarlo antes."
            )
        self._provider = provider
        self._image = image
        self._media_type = media_type
        self.last_metadata: CallMetadata | None = None

    def extract(self, document: SourceDocument) -> ProductDnaDraft:
        """Pide al modelo los atributos visibles en la imagen.

        `analyze_image()` devuelve texto libre, no salida estructurada: no
        todos los proveedores admiten esquema en la ruta de visión. Si el
        modelo no devuelve JSON legible se lanza `ProviderResponseError` en vez
        de devolver un borrador vacío, que se confundiría con «la imagen no
        aportaba nada».
        """
        prompt = load_prompt(PROMPT_ID, PROMPT_VERSION)
        respuesta = self._provider.analyze_image(
            self._image,
            prompt.render(tipo_documento=document.kind),
            media_type=self._media_type,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
        )
        self.last_metadata = respuesta.metadata

        crudo = _extraer_json(respuesta.text)
        atributos = tuple(
            ExtractedAttribute(
                name=a["name"],
                value=a.get("value"),
                unit=a.get("unit"),
                status=_topar(str(a.get("status", "MISSING"))),
                confidence=a.get("confidence"),
                locator=a.get("evidence_reference"),
            )
            for a in crudo.get("attributes", [])
            if isinstance(a, dict) and a.get("name") in CATALOG
        )

        return ProductDnaDraft(summary=crudo.get("summary"), attributes=atributos)


def _extraer_json(texto: str) -> dict:
    """Recupera el objeto JSON de una respuesta de texto libre.

    Los modelos suelen envolver el JSON en explicación o en un bloque de
    código. Se busca el primer objeto balanceado en vez de exigir que la
    respuesta entera sea JSON.
    """
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ProviderResponseError("la respuesta de visión no contiene JSON")

    try:
        datos = json.loads(texto[inicio : fin + 1])
    except json.JSONDecodeError as exc:
        raise ProviderResponseError(f"JSON inválido en la respuesta de visión: {exc}") from exc

    if not isinstance(datos, dict):
        raise ProviderResponseError("la respuesta de visión no es un objeto")
    return datos
