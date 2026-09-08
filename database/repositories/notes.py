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

    def excludes(self, *, on_date: date, heading: str, terms: Sequence[str]) -> str | None:
        """La nota que EXCLUYE la mercancía de la partida, si existe.

        Sin corpus cargado devuelve `None`, que significa «no consta exclusión»
        y no «no hay exclusión». La diferencia la declara `hay_corpus()`.
        """
        if not terms:
            return None

        return self._session.scalar(
            sa.select(LegalRule.text)
            .where(
                _vigentes(on_date),
                sa.or_(
                    LegalRule.path.ilike(f"%capítulo {heading[:2]}%"),
                    LegalRule.rule_number.startswith(heading[:2]),
                ),
                sa.or_(*(LegalRule.text.ilike(f"%{t}%") for t in terms if t.strip())),
            )
            .limit(1)
        )
