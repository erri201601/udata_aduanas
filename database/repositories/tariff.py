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
import re
from functools import reduce
from typing import TYPE_CHECKING

import sqlalchemy as sa
from core.rgi_engine.context import TariffCandidate

from database.models import Nico, TariffFraction, TariffHeading, UnitOfMeasure

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
    r"""¿La descripción contiene el término, ignorando acentos?

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

    LA PALABRA EMPIEZA DONDE EMPIEZA, PERO PUEDE SEGUIR

    `ILIKE '%olla%'` casaba dentro de «cebollas», «enrolladas» y «Pollachius»:
    32 partidas, las 32 falsas. `%presion%` casaba «impresión» y «compresión»,
    36 partidas donde hay 11. Por eso existía `MIN_LONGITUD_TERMINO`: un
    parche contra el subcadeneo, que a cambio tiraba «OLLA», la palabra que
    más discrimina en una olla a presión.

    Se ancla al INICIO de palabra (`\m`) y no al final: la tarifa escribe
    «juegos», «ollas», «válvulas» en plural, y anclar los dos extremos dejaba
    «JUEGO» en cero coincidencias donde hay 16. Medido el 23-sep sobre la
    jerarquía completa:

        OLLA     32 → 0     todas eran falsas
        PRESION  36 → 11
        JUEGO    16 → 16    el plural se conserva
    """
    return sa.func.unaccent(_texto_completo()).op("~*")(
        sa.func.concat(r"\m", sa.func.unaccent(_como_literal(termino)))
    )


def _como_literal(termino: str) -> str:
    """El término, con sus metacaracteres de expresión regular neutralizados.

    Un término sale de la descripción de una mercancía, que es texto libre: un
    `(`, un `*` o un `+` convertirían el patrón en otra cosa o lo harían
    fallar. Se escapan todos.
    """
    return re.sub(r"([\\^$.|?*+()\[\]{}])", r"\\\1", termino)


#: Alias de `tariff_headings` para la partida (4) y la subpartida (6) de cada
#: fracción. Dos, porque una fracción cuelga de las dos a la vez.
_PARTIDA = sa.orm.aliased(TariffHeading, name="partida")
_SUBPARTIDA = sa.orm.aliased(TariffHeading, name="subpartida")


def _texto_completo() -> sa.ColumnElement[str]:
    """La descripción de la fracción MÁS la de su partida y su subpartida.

    Una descripción de fracción no se sostiene sola, y no es un defecto del
    catálogo: es como se lee la LIGIE. La 73239305 dice «De acero
    inoxidable.» y no dice de qué; el sujeto está en la 7323, «Artículos de
    uso doméstico y sus partes, de fundición, hierro o acero». Medido: **3 683
    de las 8 136 descripciones (45 %) tienen menos de 25 caracteres** y 2 104
    empiezan por «Los demás».

    Buscar sólo en la fracción es buscar en fragmentos sin sujeto. Con la
    jerarquía, una vajilla de porcelana pasó de 8 candidatas equivocadas a la
    6911 sola, que es «Vajilla y demás artículos de uso doméstico… de
    porcelana» (Persona 1, 23-sep).

    `coalesce` y no `join` obligatorio: una fracción cuya partida no esté
    cargada sigue buscándose por su propio texto en vez de desaparecer.
    """
    return (
        TariffFraction.description
        + sa.literal(" ")
        + sa.func.coalesce(_PARTIDA.description, "")
        + sa.literal(" ")
        + sa.func.coalesce(_SUBPARTIDA.description, "")
    )


def _con_jerarquia(consulta: sa.Select) -> sa.Select:
    """Engancha partida y subpartida. Toda consulta que use `_casa` lo necesita."""
    return consulta.outerjoin(
        _PARTIDA,
        sa.and_(_PARTIDA.code == TariffFraction.heading, _PARTIDA.level == 4),
    ).outerjoin(
        _SUBPARTIDA,
        sa.and_(_SUBPARTIDA.code == TariffFraction.subheading, _SUBPARTIDA.level == 6),
    )


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
    """Cuántos términos casa UNA MISMA fracción, en la mejor que tenga la partida.

    El orden de las agregaciones es lo que decide, y elegirlo mal tiene un
    fallo concreto detrás.

    ANTES: sumar, por cada término, si ALGUNA fracción de la partida lo casaba.
    Eso mide «cuántas de estas palabras aparecen en algún sitio bajo esta
    partida», que en una partida residual no significa nada. Para un cable de
    acero galvanizado, la 8479 —«Las demás máquinas y aparatos mecánicos con
    función propia»— casaba CINCO de seis términos y ganaba a la 7312, que es
    la correcta y casaba cuatro. Pero los cinco venían de fracciones distintas
    y sin relación entre sí:

        ACERO → 84798107   ·   CABLE → 84794002   ·   FIBRA → 84793001
        CONSTRUCCION → 84791001   ·   GALVANIZADO → 84798103

    Ninguna de ellas describe un cable. El cajón de sastre ganaba por ser
    heterogéneo, y el motor resolvía en RGI 1 que un cable de acero era una
    máquina de control numérico para galvanizado continuo (Persona 1, 28-sep,
    a partir del dictamen humano del caso).

    AHORA: contar los términos que casa CADA fracción con su propio texto —el
    suyo más el de su partida y su subpartida— y quedarse con el máximo. Una
    partida comprende la mercancía cuando UNA de sus fracciones la describe,
    no cuando seis fracciones distintas mencionan una palabra cada una.

    Con el mismo cable: la 7312 pasa a 4 —los cuatro en la 73121007— y la 8479
    baja de 5 a menos de 3, fuera de las candidatas.
    """
    utiles = _terminos_utiles(terms)
    if not utiles:
        return sa.literal(0)
    por_fraccion = reduce(operator.add, (sa.case((_casa(t), 1), else_=0) for t in utiles))
    return sa.func.max(por_fraccion)


class TariffCatalogRepository:
    """`TariffCatalog` respaldado por PostgreSQL."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def headings(self, *, on_date: date, terms: Sequence[str]) -> Sequence[TariffCandidate]:
        """Partidas (4 dígitos) que comprenden la mercancía según los términos.

        Se agrupa por partida porque la tabla guarda fracciones de 8 dígitos:
        la partida no es una fila, es el prefijo que comparten varias.

        SÓLO LAS QUE MÁS TÉRMINOS CUBREN, NO TODAS LAS QUE ROZAN UNO

        `_coincide` es un OR: una partida que casa UNA palabra de seis entra
        igual que la que casa cinco. Antes se devolvían todas y `coincidencias`
        sólo ordenaba — pero la RGI 3 c) elige «la última en orden numérico» y
        no mira ese orden, así que el ruido acababa ganando. Un estropajo de
        acero llegó a clasificarse en 9001, elementos de óptica.

        Ahora entran sólo las del MEJOR nivel de cobertura que exista para esa
        mercancía. No es un umbral escrito a mano —probé ≥2 y ≥3 y dejaban una
        vajilla en cero candidatas—: es el máximo que se alcance, así que nunca
        devuelve vacío si algo casó. Medido el 23-sep: el estropajo pasa de 60
        candidatas —última 9605— a una sola, la 7323, que es «lana de hierro o
        acero; esponjas, estropajos y artículos similares».
        """
        cobertura = _coincidencias(terms)
        # La cobertura más alta que alcance cualquier partida. Se ordena y se
        # toma la primera en vez de envolver en `max(...)`: `cobertura` ya es
        # una suma de agregados, y Postgres no admite agregados anidados.
        mejor = (
            _con_jerarquia(sa.select(cobertura.label("cobertura")))
            .where(_vigentes(on_date), _coincide(terms))
            .group_by(TariffFraction.heading)
            .order_by(sa.desc("cobertura"))
            .limit(1)
            .scalar_subquery()
        )
        filas = self._session.execute(
            _con_jerarquia(
                sa.select(
                    TariffFraction.heading,
                    sa.func.min(TariffFraction.description).label("description"),
                    sa.func.max(TariffFraction.specificity).label("specificity"),
                    cobertura.label("coincidencias"),
                    _un_source_id(),
                )
            )
            .where(_vigentes(on_date), _coincide(terms))
            .group_by(TariffFraction.heading)
            .having(cobertura >= mejor)
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

    def fraccion_existe(self, *, on_date: date, code: str) -> bool:
        """¿La fracción de 8 dígitos está en la TIGIE vigente ese día?

        Aquí y no en el router por lo mismo que los NICO y las unidades: es
        catálogo. Y se pregunta CON FECHA porque una fracción derogada existió
        de verdad: un veredicto sobre una operación de 2022 puede citar una que
        hoy ya no está, y rechazarla por no estar vigente HOY sería evaluar una
        operación histórica con la tarifa posterior (regla 5 de CLAUDE.md).
        """
        return (
            self._session.scalar(
                sa.select(TariffFraction.id)
                .where(_vigentes(on_date), TariffFraction.code == code)
                .limit(1)
            )
            is not None
        )

    def hay_fracciones(self, *, on_date: date) -> bool:
        """¿Hay tarifa cargada para esa fecha? Sin ella no se puede acusar a nadie.

        Misma disciplina que `hay_unidades`, y por el mismo motivo: un catálogo
        vacío no demuestra que una fracción no exista, sólo que no lo sabemos.
        Sin esta pregunta, el guardarraíl del veredicto humano rechazaba TODO en
        cualquier entorno sin tarifa —lo descubrieron los tests de integración,
        que trabajan sobre una base sin catálogo— y habría rechazado también en
        una instalación nueva del cliente.
        """
        return (
            self._session.scalar(sa.select(TariffFraction.id).where(_vigentes(on_date)).limit(1))
            is not None
        )

    def hermanas_de(self, *, on_date: date, code: str) -> tuple[str, ...]:
        """Las fracciones que SÍ existen en la subpartida de `code`, ese día.

        Para poder decirle a quien teclea una fracción inexistente cuáles hay
        en su lugar. Devuelve catálogo, no una propuesta: el sistema no sugiere
        una fracción —eso lo decide la persona— sólo le enseña lo que existe.
        """
        if len(code) < 6:
            return ()
        filas = self._session.scalars(
            sa.select(TariffFraction.code)
            .where(_vigentes(on_date), TariffFraction.subheading == code[:6])
            .order_by(TariffFraction.code)
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
