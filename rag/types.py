"""Tipos del RAG jurídico (§27).

LA VIGENCIA VA POR CHUNK, NO POR DOCUMENTO

La Ley Aduanera como documento tiene una fecha de publicación, pero el
artículo 36-A se reformó en una fecha y el artículo 1 viene de 1995. Si la
vigencia fuera del documento, preguntar «qué estaba vigente el 15-03-2024»
devolvería el documento entero en su última versión, y se citaría un texto de
artículo que ese día no existía.

La regla 5 del CLAUDE.md —nunca evaluar una operación histórica con regulación
posterior— no se puede cumplir con vigencia por documento. Es por chunk o no
sirve.

`data_origin` TAMBIÉN VA POR CHUNK

Es lo que impide que un fixture acabe siendo fundamento jurídico. El contrato
de evidencia exige `source_id`, `document_ref`, `valid_from` y `content_hash`,
y ninguno mira la procedencia: un chunk de prueba con un `source_id` inventado
satisface el contrato y contaría como norma. Con `data_origin` en la fila, un
chunk `SYNTHETIC` se puede rechazar antes de llegar ahí.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Los cinco de §33. Un chunk que no declare el suyo no se indexa.
DataOrigin = Literal["OFFICIAL", "PUBLIC", "LICENSED", "SYNTHETIC", "HUMAN_VALIDATED"]

#: Sólo estos pueden sostener una afirmación jurídica (§8.1). `SYNTHETIC` no
#: está, y por eso un fixture nunca puede convertirse en fundamento.
ORIGENES_QUE_FUNDAMENTAN: Final[frozenset[str]] = frozenset(
    {"OFFICIAL", "LICENSED", "HUMAN_VALIDATED"}
)


class LegalChunk(BaseModel):
    """Un fragmento recuperable de una norma, con su propia vigencia.

    La unidad es el artículo o la fracción, no el párrafo ni el documento: es
    lo que se cita en un dictamen («artículo 36-A, fracción I») y por tanto lo
    que tiene que poder recuperarse y referenciarse entero.
    """

    model_config = ConfigDict(frozen=True)

    # ── Identidad y procedencia ──────────────────────────────────────────────
    source_id: Any | None = None
    """Fuente registrada de la que salió. Lo exige el Evidence Contract."""

    document_id: Any | None = None
    document: str
    """Nombre del instrumento: «Ley Aduanera», «RGCE 2024»."""

    legal_rule_id: Any | None = None
    """La fila de `regulatory.legal_rules` de la que salió este chunk.

    Es lo que cierra el círculo entre lo que el RAG cita y lo que el Sentinel
    puede auditar: `classification_decisions.legal_rule_ids` guarda ids de
    normas, no de chunks, así que sin esto una decisión no podía contrastarse
    contra un cambio normativo aunque hubiera guardado sus citas.

    `None` cuando el chunk no tiene una norma detrás — pasa con corpus
    cargado antes de que existiera la columna, y con fixtures. No es un
    error: es una cita que no se puede auditar, y se sabe."""

    article: str
    """Identificador citable: «36-A», «36-A fracción I», «Transitorio Segundo»."""

    path: str | None = None
    """Ubicación jerárquica: «Título Tercero > Capítulo Único > Artículo 36-A»."""

    # ── Contenido ────────────────────────────────────────────────────────────
    text: str
    heading: str | None = None

    # ── Vigencia, por chunk ──────────────────────────────────────────────────
    valid_from: date
    """Desde cuándo rige ESTE texto, no el documento."""

    valid_to: date | None = None
    """`None` = vigente. Nunca se rellena con una fecha supuesta (§14)."""

    # ── Procedencia y verificabilidad ────────────────────────────────────────
    data_origin: DataOrigin
    """De dónde salió. Sin esto un fixture podría pasar por norma."""

    content_hash: str
    """sha256 del texto normalizado. Hace la cita verificable: una URL de
    gobierno puede cambiar de contenido sin cambiar de dirección."""

    published_at: date | None = None
    url: str | None = None

    embedding: list[float] | None = Field(default=None, repr=False)
    """Se calcula al indexar. Fuera del `repr` porque son cientos de números
    que llenarían cualquier log o traza."""

    @property
    def puede_fundamentar(self) -> bool:
        """¿Este chunk puede sostener una afirmación jurídica?

        Un chunk `SYNTHETIC` no, por muy completo que esté. Es la comprobación
        que impide que un fixture se convierta en fundamento.
        """
        return self.data_origin in ORIGENES_QUE_FUNDAMENTAN

    def vigente_en(self, fecha: date) -> bool:
        """¿Regía este texto en esa fecha? (§14, regla 5 del CLAUDE.md)."""
        if self.valid_from > fecha:
            return False
        return self.valid_to is None or self.valid_to >= fecha

    def cita(self) -> str:
        """Cómo se cita en un dictamen."""
        return f"{self.document}, artículo {self.article}"


def hash_contenido(texto: str) -> str:
    """sha256 del texto normalizado.

    Se normalizan los espacios porque el mismo artículo copiado de dos PDFs
    distintos difiere en saltos de línea, y eso no lo hace un texto distinto.
    """
    normalizado = " ".join(texto.split())
    return f"sha256:{hashlib.sha256(normalizado.encode('utf-8')).hexdigest()}"
