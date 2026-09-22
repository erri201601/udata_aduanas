"""Catálogo arancelario sobre `regulatory.tariff_fractions`.

Implementa el puerto `TariffCatalog` que declara el RGI Engine. El motor no
sabe que hay una base detrás: pide partidas, subpartidas y fracciones vigentes
en una fecha, y aquí se resuelven.

LA VIGENCIA NO ES UN FILTRO OPCIONAL

`on_date` es obligatorio en las tres consultas porque en la tarifa conviven
versiones del mismo código. Hoy mismo `84713001` tiene dos filas: una que
venció el 2022-06-06 y otra que rige desde el día siguiente. Clasificar una
operación de 2024 con la versión equivocada da un resultado que parece
correcto y no lo es (§14 del maestro).

Por eso el filtro se aplica en SQL y no después: si se trajeran todas las
versiones y se descartaran en Python, cualquier consulta que se olvidara del
paso devolvería la fila incorrecta en silencio.
"""

from __future__ import annotations

import operator
from functools import reduce
from typing import TYPE_CHECKING

import sqlalchemy as sa
from core.rgi_engine.context import TariffCandidate

from database.models import Nico, TariffFraction, UnitOfMeasure

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from decimal import Decimal

    from sqlalchemy.orm import Session

#: Tope de candidatos por consulta. El RGI evalúa cada uno contra las notas
#: legales; cien partidas no ayudan a decidir, sólo hacen la traza ilegible.
MAX_CANDIDATOS = 25


def _un_source_id() -> sa.ColumnElement:
    """Un `source_id` cualquiera del grupo, como UUID.

    PostgreSQL no tiene `min(uuid)`, así que se agrega sobre texto y se
    devuelve al tipo. Cuál se elija da igual y por eso se toma el mínimo, que
    al menos es determinista: una partida no es una fila —es el prefijo que
    comparten varias fracciones— y todas vienen del mismo documento de tarifa.
    """
    return sa.cast(
        sa.func.min(sa.cast(TariffFraction.source_id, sa.Text)), sa.Uuid(as_uuid=True)
    ).label("source_id")


def _vigentes(on_date: date) -> sa.ColumnElement[bool]:
    """`valid_from <= fecha <= valid_to`, con `valid_to = NULL` = vigente.

    Es la regla 5 del CLAUDE.md escrita una sola vez, para que ninguna consulta
    pueda olvidarla.
    """
    return sa.and_(
        TariffFraction.valid_from <= on_date,
        sa.or_(TariffFraction.valid_to.is_(None), TariffFraction.valid_to >= on_date),
    )


def _casa(termino: str) -> sa.ColumnElement[bool]:
    """¿La descripción contiene el término, ignorando acentos?

    `unaccent` a los DOS lados, y no sólo al término, porque el desajuste es
    real y silencioso: un pedimento se escribe en mayúsculas y sin acentos
    —«COMPUTADORAS PORTATILES»— y la tarifa sí los lleva —«portátiles»—. Con
    `ILIKE` a secas eso no casa: comprobado contra la base, «portatiles»
    devolvía 0 fracciones y «portátiles» 11; «algodon» 0 y «algodón» 74.

    El efecto no era no encontrar nada: era encontrar lo que no toca. Las
    palabras sin acento seguían casando, y la prosa larga del capítulo 98
    —operaciones especiales, 411 caracteres de media frente a 60 del resto—
    se llevaba los candidatos con términos genéricos. Unos cables eléctricos
    acababan clasificados en 9806.
    """
    return sa.func.unaccent(TariffFraction.description).ilike(sa.func.unaccent(f"%{termino}%"))


def _terminos_utiles(terms: Sequence[str]) -> list[str]:
    return [t for t in terms if t.strip()]


def _coincide(terms: Sequence[str]) -> sa.ColumnElement[bool]:
    """Filtro: la fracción casa con AL MENOS uno de los términos.

    Búsqueda simple a propósito: la semántica la aporta el RAG (§27). Aquí
    sólo se reduce el universo —8 136 fracciones de los 97 capítulos— a un
    puñado de candidatos que el motor pueda evaluar contra las notas legales.
    """
    utiles = _terminos_utiles(terms)
    if not utiles:
        return sa.true()
    return sa.or_(*(_casa(t) for t in utiles))


def _coincidencias(terms: Sequence[str]) -> sa.ColumnElement[int]:
    """Cuántos términos DISTINTOS casa la partida. Es el orden de pertinencia.

    Se cuenta por término y no por fila: `max(...)` dentro de cada término
    responde «esta partida contiene esta palabra en alguna de sus fracciones»,
    y sumar esos máximos da cuántas palabras de la consulta cubre. Sumar filas
    en vez de términos premiaría a la partida con más fracciones, que es otra
    cosa.

    Ordenar sólo por `specificity` —lo que se hacía antes— deja que una
    partida que casa una palabra genérica adelante a la que casa todas.
    """
    utiles = _terminos_utiles(terms)
    if not utiles:
        return sa.literal(0)
    return reduce(operator.add, (sa.func.max(sa.case((_casa(t), 1), else_=0)) for t in utiles))


class TariffCatalogRepository:
    """`TariffCatalog` respaldado por PostgreSQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def headings(self, *, on_date: date, terms: Sequence[str]) -> Sequence[TariffCandidate]:
        """Partidas (4 dígitos) cuyo texto coincide con los términos.

        Se agrupa por partida porque la tabla guarda fracciones de 8 dígitos:
        la partida no es una fila, es el prefijo que comparten varias.
        """
        filas = self._session.execute(
            sa.select(
                TariffFraction.heading,
                sa.func.min(TariffFraction.description).label("description"),
                sa.func.max(TariffFraction.specificity).label("specificity"),
                _coincidencias(terms).label("coincidencias"),
                _un_source_id(),
            )
            .where(_vigentes(on_date), _coincide(terms))
            .group_by(TariffFraction.heading)
            .order_by(sa.desc("coincidencias"), sa.desc("specificity"), TariffFraction.heading)
            .limit(MAX_CANDIDATOS)
        ).all()

        return [
            TariffCandidate(
                code=f.heading,
                text=f.description,
                level="HEADING",
                source_id=f.source_id,
                specificity=f.specificity or 0,
            )
            for f in filas
        ]

    def subheadings(self, *, on_date: date, heading: str) -> Sequence[TariffCandidate]:
        """Subpartidas (6 dígitos) que dependen de una partida."""
        filas = self._session.execute(
            sa.select(
                TariffFraction.subheading,
                sa.func.min(TariffFraction.description).label("description"),
                sa.func.max(TariffFraction.specificity).label("specificity"),
                _un_source_id(),
            )
            .where(_vigentes(on_date), TariffFraction.heading == heading)
            .group_by(TariffFraction.subheading)
            .order_by(sa.desc("specificity"), TariffFraction.subheading)
            .limit(MAX_CANDIDATOS)
        ).all()

        return [
            TariffCandidate(
                code=f.subheading,
                text=f.description,
                level="SUBHEADING",
                source_id=f.source_id,
                specificity=f.specificity or 0,
            )
            for f in filas
        ]

    def fractions(self, *, on_date: date, subheading: str) -> Sequence[TariffCandidate]:
        """Fracciones mexicanas (8 dígitos) de una subpartida.

        Aquí es donde más importa la vigencia: es el nivel que se declara en el
        pedimento, y el que tiene versiones solapadas en la tarifa real.
        """
        filas = self._session.scalars(
            sa.select(TariffFraction)
            .where(_vigentes(on_date), TariffFraction.subheading == subheading)
            .order_by(TariffFraction.specificity.desc(), TariffFraction.code)
            .limit(MAX_CANDIDATOS)
        ).all()

        return [
            TariffCandidate(
                code=f.code,
                text=f.description,
                level="FRACTION",
                source_id=f.source_id,
                specificity=f.specificity,
            )
            for f in filas
        ]

    def nicos(self, *, on_date: date, fraction_code: str) -> tuple[str, ...] | None:
        """Los NICO vigentes de una fracción, ordenados.

        Vive aquí y no en el router porque es catálogo: el día que otro motor
        necesite saber qué NICO existen, tiene que encontrarlo en el catálogo
        (Persona 1, 21-sep).

        TRES RESPUESTAS DISTINTAS, Y LA DIFERENCIA IMPORTA

        - `None`: la fracción no está vigente en esa fecha. No se puede afirmar
          nada sobre su NICO, y decir «no existe» sería culpar al pedimento de
          un hueco del catálogo.
        - `()`: la fracción existe y no tiene NICO cargados. Tampoco permite
          acusar: es un hueco nuestro.
        - Con códigos: eso sí permite decir si el declarado está entre ellos.
        """
        existe = self._session.scalar(
            sa.select(TariffFraction.id)
            .where(_vigentes(on_date), TariffFraction.code == fraction_code)
            .limit(1)
        )
        if existe is None:
            return None

        filas = self._session.scalars(
            sa.select(Nico.code)
            .join(TariffFraction, TariffFraction.id == Nico.tariff_fraction_id)
            .where(
                _vigentes(on_date),
                TariffFraction.code == fraction_code,
                Nico.valid_from <= on_date,
                sa.or_(Nico.valid_to.is_(None), Nico.valid_to >= on_date),
            )
            .order_by(Nico.code)
        ).all()
        return tuple(filas)

    def unidad_existe(self, *, on_date: date, code: str) -> bool:
        """¿La unidad declarada está en el Apéndice 7 del Anexo 22, ese día?

        Aquí y no en el router por lo mismo que los NICO: es catálogo. Devuelve
        `False` sólo cuando el catálogo está cargado y la clave no aparece —
        quien llama decide qué hacer si el catálogo estuviera vacío, y para eso
        existe `hay_unidades`.
        """
        return (
            self._session.scalar(
                sa.select(UnitOfMeasure.id)
                .where(
                    UnitOfMeasure.code == code,
                    UnitOfMeasure.valid_from <= on_date,
                    sa.or_(UnitOfMeasure.valid_to.is_(None), UnitOfMeasure.valid_to >= on_date),
                )
                .limit(1)
            )
            is not None
        )

    def hay_unidades(self, *, on_date: date) -> bool:
        """¿Hay catálogo de unidades cargado? Sin él no se puede acusar a nadie."""
        return (
            self._session.scalar(
                sa.select(UnitOfMeasure.id)
                .where(
                    UnitOfMeasure.valid_from <= on_date,
                    sa.or_(UnitOfMeasure.valid_to.is_(None), UnitOfMeasure.valid_to >= on_date),
                )
                .limit(1)
            )
            is not None
        )

    def igi_rate(self, *, on_date: date, fraction_code: str) -> Decimal | None:
        """La tasa de IGI de una fracción, vigente en la fecha de la operación.

        `None` significa que no se sabe —la fracción no existe en la tarifa
        cargada, o existe sin tasa—, no que sea cero. La diferencia decide si un
        hallazgo se cuantifica o se queda sin monto, y una tasa inventada en
        cero produciría una cifra plausible y falsa.

        No forma parte del `TariffCatalog` que consume el motor de RGI: ese
        clasifica, y para clasificar la tasa es irrelevante. La usa el Money
        Finder, que es otra cosa.
        """
        return self._session.scalars(
            sa.select(TariffFraction.igi_rate)
            .where(_vigentes(on_date), TariffFraction.code == fraction_code)
            .limit(1)
        ).first()
