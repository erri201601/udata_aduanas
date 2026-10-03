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
                name=nombre,
                value=a.get("value"),
                unit=a.get("unit"),
                status=_topar(str(a.get("status", "MISSING"))),
                confidence=a.get("confidence"),
                locator=a.get("evidence_reference"),
            )
            for nombre, a in _atributos(crudo)
        )
        _comprobar_que_no_se_perdio_nada(crudo, atributos)

        return ProductDnaDraft(
            summary=crudo.get("summary"),
            attributes=atributos,
            missing_information=tuple(
                str(m) for m in crudo.get("missing_information", []) if isinstance(m, str)
            ),
            input_kinds=("image",),
        )


#: Claves del objeto raíz que NO son atributos. Todo lo demás que aparezca ahí
#: se interpreta como un atributo devuelto en la forma vieja.
_NO_SON_ATRIBUTOS: Final[frozenset[str]] = frozenset(
    {"summary", "attributes", "missing_information"}
)


def _atributos(crudo: dict) -> list[tuple[str, dict]]:
    """Los atributos de la respuesta, vengan en la forma que vengan.

    El prompt pide una LISTA bajo `attributes`, cada elemento con su `name`.
    Pero esta ruta no usa salida estructurada —no todos los proveedores la
    admiten en visión— así que nada obliga al modelo a obedecer, y de hecho no
    obedecía: devolvía un objeto con un atributo POR CLAVE.

    Eso costó una ficha técnica entera. El modelo leyó producto, marca, modelo,
    SKU, fabricante y materiales, todos `EXTRACTED` con su localización, y el
    parser devolvió cero porque buscaba una lista que no estaba. Nadie lo vio
    en dos semanas porque este código no lo llamaba nadie.

    Se aceptan las dos formas. Pedir una en el prompt y entender sólo ésa es
    apostar a que un modelo de lenguaje no improvise.
    """
    en_lista = crudo.get("attributes")
    if isinstance(en_lista, list):
        crudos = [
            (a["name"], a) for a in en_lista if isinstance(a, dict) and a.get("name") in CATALOG
        ]
    else:
        crudos = [
            (clave, valor)
            for clave, valor in crudo.items()
            if clave in CATALOG and isinstance(valor, dict)
        ]

    salida: list[tuple[str, dict]] = []
    for nombre, a in crudos:
        salida.extend(_desplegar(nombre, a))
    return salida


def _desplegar(nombre: str, atributo: dict) -> list[tuple[str, dict]]:
    """Un atributo, o varios si `technical_attributes` trae una bolsa.

    `technical_attributes` es del catálogo del §16 y su valor es, por
    naturaleza, un objeto: «construcción 6x19, diámetro 10 mm, alma de fibra».
    Guardarlo como un solo atributo con todo dentro lo dejaría inservible para
    el motor, que busca `diametro_mm` por su nombre.

    Se despliega en uno por clave, HEREDANDO el estado y la confianza del
    padre: se leyeron en el mismo acto, y darles un estado mejor del que el
    modelo declaró para el conjunto sería subir una confianza que nadie dio.
    """
    valor = atributo.get("value")
    if nombre != "technical_attributes" or not isinstance(valor, dict):
        return [(nombre, {**atributo, "value": _texto(valor)})]

    return [
        (str(clave), {**atributo, "value": _texto(v)})
        for clave, v in valor.items()
        if v is not None and str(v).strip()
    ]


def _texto(valor: object) -> str | None:
    """El valor como texto, o `None` si no aporta.

    Un modelo que devuelve `19` en vez de `"19"` no está equivocado, y tirar el
    atributo por eso perdería un dato bueno. Un objeto anidado se aplana a
    `clave: valor` en vez de perderse: es peor información que tenerla suelta,
    pero mucho mejor que ninguna.
    """
    if valor is None:
        return None
    if isinstance(valor, str):
        return valor or None
    if isinstance(valor, dict):
        return "; ".join(f"{k}: {v}" for k, v in valor.items() if v is not None) or None
    if isinstance(valor, list):
        return ", ".join(str(v) for v in valor if v is not None) or None
    return str(valor)


def _comprobar_que_no_se_perdio_nada(
    crudo: dict, atributos: tuple[ExtractedAttribute, ...]
) -> None:
    """Un borrador vacío que salió de una respuesta llena es un fallo NUESTRO.

    Y tiene que doler, no pasar por «la imagen no aportaba nada»: son cosas
    opuestas y quien mire la pantalla no puede distinguirlas.

    Una imagen que de verdad no dice nada devuelve un objeto sin más claves que
    las del envoltorio, y ésa sí produce un borrador vacío sin error.
    """
    if atributos:
        return
    sobrantes = set(crudo) - _NO_SON_ATRIBUTOS
    if sobrantes:
        raise ProviderResponseError(
            "la respuesta de visión trae datos que no se supieron leer "
            f"({', '.join(sorted(sobrantes)[:6])}): el formato no es el esperado"
        )


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
