"""Notas legales de sección y capítulo sobre `regulatory.legal_rules`.

Implementa el puerto `LegalNotes` del RGI Engine.

HOY NO HAY NOTAS CARGADAS

`regulatory.legal_rules` está vacía: la ingestión de Ley Aduanera y RGCE es
tarea de Persona 2 y todavía no ha entrado. Este repositorio devuelve listas
vacías, y eso NO es un fallo silencioso: la RGI 1 dice que la clasificación se
determina por los textos de las partidas **y por las notas**, así que sin
notas el motor no puede descartar una partida por exclusión.

Se devuelve vacío en vez de inventar una nota, y `hay_corpus()` permite que
quien orqueste avise de que la clasificación se hizo sin ellas. Una
clasificación sin notas no es inválida — es menos fundamentada, y eso tiene
que poder decirse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from database.models import LegalRule

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from sqlalchemy.orm import Session

#: Las notas de sección y capítulo se identifican por su `path`: la ingestión
#: guarda ahí la ubicación jerárquica del artículo dentro del documento. No hay
#: columna de tipo, así que el prefijo es lo único que las distingue.
PREFIJOS_NOTA = ("Nota", "Notas", "Sección", "Capítulo")


def _vigentes(on_date: date) -> sa.ColumnElement[bool]:
    """Misma regla temporal que el catálogo: nunca una norma posterior (§14)."""
    return sa.and_(
        LegalRule.valid_from <= on_date,
        sa.or_(LegalRule.valid_to.is_(None), LegalRule.valid_to >= on_date),
    )


class LegalNotesRepository:
    """`LegalNotes` respaldado por PostgreSQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def hay_corpus(self, *, on_date: date) -> bool:
        """¿Hay alguna nota cargada y vigente?

        Permite decir «se clasificó sin notas» en vez de dejar que parezca que
        se consultaron y no excluían nada.
        """
        return bool(
            self._session.scalar(
                sa.select(sa.func.count()).select_from(LegalRule).where(_vigentes(on_date))
            )
        )

    def notes_for(self, *, on_date: date, chapter: str) -> Sequence[str]:
        """Notas aplicables a un capítulo."""
        filas = self._session.scalars(
            sa.select(LegalRule.text)
            .where(
                _vigentes(on_date),
                sa.or_(
                    LegalRule.path.ilike(f"%capítulo {chapter}%"),
                    LegalRule.rule_number.startswith(chapter),
                ),
            )
            .limit(50)
        ).all()
        return list(filas)

    def excludes(
        self,
        *,
        # La firma la fija el puerto `LegalNotes` del motor, no esta clase: los
        # tres argumentos siguen ahí aunque este método ya no los use.
        on_date: date,  # noqa: ARG002
        heading: str,  # noqa: ARG002
        terms: Sequence[str],  # noqa: ARG002
    ) -> str | None:
        """Siempre `None`: aquí no se determinan exclusiones. Ver abajo.

        DEVUELVE `None` A PROPÓSITO, NO POR ESTAR SIN IMPLEMENTAR

        Antes buscaba una nota del capítulo cuyo texto contuviera alguno de los
        términos de búsqueda. Mientras `legal_rules` estuvo vacía nunca
        encontraba nada y el defecto no se veía. El 8 de septiembre Persona 2
        cargó las 92 notas reales de sección y capítulo, y entonces excluyó
        TODAS las partidas candidatas de una computadora portátil.

        La nota del Capítulo 84 dice, entre muchas otras cosas:

            «…herramientas para ser operadas por una persona y que sean
            portátiles. 14. En la partida 84.71, no se consideran los aparatos
            utilizados para la comunicación…»

        Contiene «portátiles», hablando de herramientas de mano. Y contiene una
        exclusión real de la partida 84.71 — de aparatos de comunicación, que
        no es lo que estamos clasificando.

        Ahí está el problema de fondo: **que un término aparezca en una nota no
        significa que la nota excluya esta mercancía**, y decidir si una
        exclusión aplica exige leer de qué habla, no si comparte una palabra.
        Eso es interpretación jurídica. Hacerla con un `ILIKE` es inventar
        fundamento, y en la dirección más cara: una exclusión falsa descarta la
        partida correcta y el sistema clasifica mal con apariencia de rigor.

        Así que esta capa deja de decidirlo. `applicable()` entrega las notas
        que hay que leer, y quien pueda interpretarlas —el RAG del §27, un
        modelo con la nota recuperada delante, o una persona— decide. Devolver
        `None` significa «no consta exclusión determinista», nunca «no hay
        exclusión»; `hay_corpus()` sigue declarando si había notas que mirar.
        """
        return None

    def applicable(self, *, on_date: date, heading: str) -> Sequence[str]:
        """Notas del capítulo que mencionan explícitamente esta partida.

        No afirma que excluyan: afirma que hablan de ella y que alguien tiene
        que leerlas. Busca la partida escrita como la escribe la LIGIE —`84.71`
        con punto— y también sin él, porque las dos formas aparecen.
        """
        capitulo, partida = heading[:2], heading[:4]
        con_punto = f"{partida[:2]}.{partida[2:]}"

        filas = self._session.scalars(
            sa.select(LegalRule.text)
            .where(
                _vigentes(on_date),
                sa.or_(
                    LegalRule.path.ilike(f"%capítulo {capitulo}%"),
                    LegalRule.rule_number.startswith(capitulo),
                ),
                sa.or_(
                    LegalRule.text.ilike(f"%{con_punto}%"),
                    LegalRule.text.ilike(f"%partida {partida}%"),
                ),
            )
            .limit(10)
        ).all()
        return list(filas)
