"""Recuperación con filtro temporal y de procedencia (§14, §27).

DOS FILTROS QUE NO SON OPCIONALES

**Temporal.** Una consulta sobre una operación de 2024 nunca puede recuperar
una norma que entró en vigor en 2026. Es la regla 5 del CLAUDE.md, y se aplica
aquí —en el borde— además de en el almacén: si un día alguien escribe otro
`ChunkStore` y se le olvida, esta capa lo sigue cumpliendo.

**De procedencia.** Un chunk `SYNTHETIC` no puede sostener una afirmación
jurídica por muy completo que esté. El contrato de evidencia exige
`source_id`, `document_ref`, `valid_from` y `content_hash`, y ninguno mira
`data_origin`: un fixture con un `source_id` inventado satisfaría el contrato
y contaría como norma. El filtro va aquí porque es el último punto donde se
puede parar antes de que un chunk llegue a construir evidencia.

SIN FUENTE SUFICIENTE, SE DICE

`Recuperacion.hay_fundamento` distingue «no encontré nada» de «encontré cosas
que no fundamentan». La respuesta correcta cuando no hay es «No tengo
evidencia suficiente en la base cargada», nunca una cita inventada.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from rag.types import LegalChunk

if TYPE_CHECKING:
    from rag.ports import ChunkStore, Embedder

#: Cuántos chunks se recuperan por consulta. Más no mejora la respuesta: la
#: diluye, y alarga el prompt hasta que el modelo pierde el hilo.
LIMITE_POR_DEFECTO = 8


class Recuperacion(BaseModel):
    """Lo recuperado, y qué se puede hacer con ello."""

    model_config = ConfigDict(frozen=True)

    chunks: tuple[LegalChunk, ...] = ()
    on_date: date
    descartados_por_vigencia: int = 0
    """Coincidían, pero no regían ese día."""
    descartados_por_origen: int = 0
    """Regían, pero no pueden fundamentar: fixtures, o fuentes no oficiales."""

    @property
    def hay_fundamento(self) -> bool:
        """¿Hay al menos un chunk que pueda sostener una afirmación jurídica?"""
        return any(c.puede_fundamentar for c in self.chunks)

    @property
    def citas(self) -> tuple[str, ...]:
        """Las citas, para acompañar la respuesta. Nunca se inventan."""
        return tuple(c.cita() for c in self.chunks if c.puede_fundamentar)

    def sin_evidencia(self) -> str:
        """El mensaje cuando no hay con qué responder.

        Se devuelve tal cual, sin adornar: decir «no tengo evidencia» es una
        respuesta correcta, y disfrazarla de respuesta parcial no lo sería.
        """
        return (
            "No tengo evidencia suficiente en la base cargada para responder "
            f"con fundamento sobre la fecha {self.on_date.isoformat()}."
        )


def recuperar(
    consulta: str,
    *,
    on_date: date,
    store: ChunkStore,
    embedder: Embedder | None = None,
    limit: int = LIMITE_POR_DEFECTO,
    permitir_no_fundamentables: bool = False,
) -> Recuperacion:
    """Recupera normas vigentes en una fecha.

    `on_date` es obligatorio y sin valor por defecto: hacerlo opcional
    convertiría la regla temporal en algo que se puede olvidar.

    `permitir_no_fundamentables` existe para poder inspeccionar el índice en
    desarrollo. Está en `False` por defecto y quien lo active lo hace a
    sabiendas.
    """
    embedding = None
    if embedder is not None:
        embedding = list(embedder.embed([consulta])[0])

    candidatos = list(
        store.search(
            on_date=on_date,
            query_embedding=embedding,
            terms=terminos_de_consulta(consulta),
            limit=limit * 2,
            solo_fundamentables=not permitir_no_fundamentables,
        )
    )

    vigentes = [c for c in candidatos if c.vigente_en(on_date)]
    if permitir_no_fundamentables:
        admitidos = vigentes
    else:
        admitidos = [c for c in vigentes if c.puede_fundamentar]

    return Recuperacion(
        chunks=tuple(admitidos[:limit]),
        on_date=on_date,
        descartados_por_vigencia=len(candidatos) - len(vigentes),
        descartados_por_origen=len(vigentes) - len(admitidos),
    )


def terminos_de_consulta(consulta: str) -> tuple[str, ...]:
    """Palabras con las que buscar por texto, sin las vacías.

    Público porque quien presenta un resultado tiene que poder decir con qué
    se buscó: el Copilot enseña cuántos de estos términos casa cada pasaje,
    y sin acceso a la lista esa cifra no se podría calcular ni comprobar.

    Búsqueda simple a propósito: la semántica la aporta el vector. Esto sólo
    acota el conjunto para que el almacén no tenga que leerlo entero.
    """
    vacias = {
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "que",
        "en",
        "y",
        "a",
        "un",
        "una",
        "para",
        "con",
        "por",
        "es",
        "se",
        "al",
        "lo",
        "cual",
        "qué",
    }
    palabras = [p.strip(".,;:¿?¡!()").lower() for p in consulta.split()]
    return tuple(p for p in palabras if len(p) > 2 and p not in vacias)[:8]
