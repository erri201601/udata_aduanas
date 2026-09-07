"""Puertos del Product DNA Engine: lo que el motor necesita del exterior.

Mismo criterio que el RGI Engine: el motor no llama a ningún proveedor de IA ni
toca la base. Declara qué necesita y alguien se lo inyecta. Eso permite probar
la parte que importa —el saneamiento de la extracción— con extractores
deterministas, sin gastar una sola llamada y sin depender de que un modelo
responda igual dos veces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from core.product_dna.types import ProductDnaDraft, SourceDocument


@runtime_checkable
class Extractor(Protocol):
    """Convierte un documento en atributos candidatos.

    Lo que devuelve es una PROPUESTA, no un resultado: el motor la sanea
    después. Un extractor puede equivocarse —marcar como `OBSERVED` algo que
    dedujo, o rellenar un campo para que la salida se vea completa— y el motor
    es quien lo corrige. Por eso la validación no vive aquí.
    """

    def extract(self, document: SourceDocument) -> ProductDnaDraft:
        """Atributos candidatos del documento."""
        ...
