"""Regulatory Sentinel (§32) — qué ha cambiado en la norma y qué nos toca.

Esta pantalla tiene una tentación propia, distinta a la del tablero: parecer
que vigila. Un centinela que enseña «0 alertas» sobre un vigilante que nunca
arrancó está mintiendo con un cero, y el cero se lee como «todo en orden».

TRES REGLAS QUE LO DEFINEN

1. **Distinguir «sin novedades» de «sin vigilancia».** `regulatory_events` es
   la salida del DOF Regulatory Watcher. Mientras esa tabla esté vacía porque
   el vigilante no existe todavía, se dice —`vigilancia_automatica: false`—
   en vez de presentar la ausencia de eventos como calma.

2. **La reforma se lee del corpus, no de un feed — y no toda vigencia es
   reforma.** Cada `legal_rule` trae su propia vigencia (§14), pero una fecha
   `valid_from` repetida NO basta para hablar de reforma. Una norma empieza a
   regir por dos motivos distintos: porque el DOF la modificó ese día, o
   porque su documento entero entró en vigor. Llamar «ola de reforma» a lo
   segundo es falso: la RGCE 2026 trae ~535 reglas con `valid_from =
   2026-01-01` porque la resolución anual se sustituye completa, no porque se
   reformaran 535 reglas. Pasaba ya con la LIGIE: sus 92 notas salían como
   «92 normas reformadas el 2022-06-07» sin que ninguna tuviera nota de
   reforma.

   Lo que distingue una cosa de la otra es `reform_note`: la Ley Aduanera
   anota «Párrafo reformado DOF 19-11-2025», y los 80 artículos con
   `valid_from = 2025-11-19` citan ese mismo día. `legal_documents.kind` NO
   sirve para decidirlo —esos 80 son reformas de verdad y su documento es
   `LAW` con la misma fecha de vigencia—, así que se expone para rotular, no
   para clasificar.

3. **El impacto sobre lo nuestro sólo se afirma si se puede trazar.** Una
   decisión únicamente puede declararse afectada por un cambio normativo si
   guardó qué normas citó. Las que no lo guardaron se cuentan aparte, como
   hueco: no se asumen limpias.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated, Final, Literal

import sqlalchemy as sa
from database.models import ClassificationDecision, LegalDocument, LegalRule, RegulatoryEvent
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import aggregate_order_by

from apps.api.db import SessionDep

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(prefix="/sentinel", tags=["sentinel"])

#: Cuántas olas de reforma se devuelven. Las viejas no dejan de importar, pero
#: una pantalla que las lista todas deja de poder leerse — por eso el total va
#: aparte (`total_olas`): lo que no cabe se cuenta, no desaparece.
TOPE_REFORMAS: Final = 12

#: Cuántas entradas en vigor sin reforma se devuelven. Mismo criterio.
TOPE_ENTRADAS: Final = 12

#: Cómo cita una fecha la nota de reforma del DOF: «DOF 19-11-2025».
FORMATO_FECHA_DOF: Final = "DD-MM-YYYY"

#: Cuántos números de artículo se muestran como muestra de cada ola.
MUESTRA_POR_OLA: Final = 6

#: Cuántas normas derogadas se listan.
TOPE_FUERA_DE_VIGENCIA: Final = 20

#: Orígenes que pueden presentarse como norma real. Los demás se marcan §33.
ORIGENES_OFICIALES: Final = frozenset({"OFFICIAL", "LICENSED", "HUMAN_VALIDATED"})


def _vigentes(on_date: date) -> sa.ColumnElement[bool]:
    """`valid_from <= fecha <= valid_to`, con `valid_to = NULL` = vigente (§14).

    Misma regla que el catálogo y que el RAG: nunca una norma posterior a la
    operación. Se repite aquí porque vive sobre `LegalRule`, no sobre chunks.
    """
    return sa.and_(
        LegalRule.valid_from <= on_date,
        sa.or_(LegalRule.valid_to.is_(None), LegalRule.valid_to >= on_date),
    )


class DocumentoVigilado(BaseModel):
    """Un instrumento del corpus y cuánto de él se está vigilando."""

    short_name: str
    title: str
    kind: str
    data_origin: str
    valid_from: date | None = None
    valid_to: date | None = None
    normas: int = 0
    """Artículos/reglas cargados de este documento."""
    es_fuente_oficial: bool = False
    """Falso = no puede fundamentar nada. Se marca SYNTHETIC en la pantalla."""


class OlaDeReforma(BaseModel):
    """Un día en que el DOF modificó normas de UN documento.

    Sólo cuenta las normas cuya `reform_note` cita ese mismo día («reformado»,
    «adicionado» o «derogado» DOF dd-mm-aaaa). No es un evento del DOF: es lo
    que el corpus permite deducir sin inventar nada. Si el watcher existiera,
    esto se cruzaría con él.
    """

    fecha: date
    documento: str
    kind: str
    normas: int
    """Normas modificadas ese día. No las que simplemente empiezan a regir."""
    muestra: list[str] = Field(default_factory=list)
    """Algunos números de artículo, para que la fecha no sea sólo una cifra."""


class EntradaEnVigor(BaseModel):
    """Normas que empiezan a regir un día SIN que conste reforma.

    No es una ola de reforma y no se presenta como tal. Dos casos:

    - `DOCUMENTO_COMPLETO`: el día coincide con la vigencia del documento. Una
      resolución anual que se sustituye entera (RGCE 2026) o una tarifa nueva
      (LIGIE 2022).
    - `SIN_REFORMA_REGISTRADA`: el día no coincide con el del documento y
      ninguna nota cita reforma. Puede ser la publicación original de la ley
      o una entrada en vigor diferida por transitorio; el corpus no dice
      cuál, así que no se afirma ninguna de las dos.
    """

    fecha: date
    documento: str
    kind: str
    normas: int
    tipo: Literal["DOCUMENTO_COMPLETO", "SIN_REFORMA_REGISTRADA"]
    muestra: list[str] = Field(default_factory=list)


class NormaFueraDeVigencia(BaseModel):
    """Norma con `valid_to`: dejó de estar vigente ese día."""

    rule_number: str
    documento: str
    valid_from: date
    valid_to: date
    encabezado: str | None = None


class ImpactoEnDecisiones(BaseModel):
    """Cuánto de lo que ya decidimos se puede contrastar contra la norma."""

    decisiones: int = 0
    con_normas_citadas: int = 0
    """Las únicas sobre las que se puede afirmar algo."""
    sin_normas_citadas: int = 0
    """Hueco declarado: no se asumen limpias, no se sabe qué citaron."""
    afectadas: int = 0
    """Citan al menos una norma que no estaba vigente en su fecha de operación."""
    trazable: bool = False
    """¿Se puede sostener el análisis de impacto con lo que hay guardado?"""


class Sentinel(BaseModel):
    """Estado de la vigilancia normativa a una fecha."""

    fecha: date
    corpus: list[DocumentoVigilado] = Field(default_factory=list)
    normas_totales: int = 0
    vigentes_en_fecha: int = 0
    """Cuántas normas del corpus estaban vigentes ese día (§14)."""
    fuera_de_vigencia_total: int = 0
    reformas: list[OlaDeReforma] = Field(default_factory=list)
    """Las `TOPE_REFORMAS` más recientes, agrupadas por documento y día."""
    total_olas: int = 0
    """Cuántas olas hay en total. Si es mayor que `len(reformas)`, las más
    viejas no caben en la lista — pero existen, y se dice."""
    entradas_en_vigor: list[EntradaEnVigor] = Field(default_factory=list)
    total_entradas_en_vigor: int = 0
    fuera_de_vigencia: list[NormaFueraDeVigencia] = Field(default_factory=list)

    eventos_dof: int = 0
    vigilancia_automatica: bool = False
    """`false` = el DOF Regulatory Watcher no ha publicado nada todavía.

    Sin esto, `eventos_dof: 0` se leería como «sin novedades en el DOF», que
    es exactamente lo contrario de lo que significa hoy.
    """

    impacto: ImpactoEnDecisiones = Field(default_factory=ImpactoEnDecisiones)

    corpus_sintetico: int = 0
    """Documentos del corpus que NO son fuente oficial (§33)."""


def _corpus(session: Session) -> list[DocumentoVigilado]:
    filas = session.execute(
        sa.select(
            LegalDocument.short_name,
            LegalDocument.title,
            LegalDocument.kind,
            LegalDocument.data_origin,
            LegalDocument.valid_from,
            LegalDocument.valid_to,
            sa.func.count(LegalRule.id),
        )
        .select_from(LegalDocument)
        .outerjoin(LegalRule, LegalRule.legal_document_id == LegalDocument.id)
        .group_by(
            LegalDocument.short_name,
            LegalDocument.title,
            LegalDocument.kind,
            LegalDocument.data_origin,
            LegalDocument.valid_from,
            LegalDocument.valid_to,
        )
        .order_by(sa.func.count(LegalRule.id).desc(), LegalDocument.short_name)
    ).all()

    return [
        DocumentoVigilado(
            short_name=short_name,
            title=title,
            kind=kind,
            data_origin=data_origin,
            valid_from=desde,
            valid_to=hasta,
            normas=normas,
            es_fuente_oficial=data_origin in ORIGENES_OFICIALES,
        )
        for short_name, title, kind, data_origin, desde, hasta, normas in filas
    ]


def _cita_su_fecha() -> sa.ColumnElement[bool]:
    """¿La nota de reforma de la norma cita el día en que empezó a regir?

    Es la señal de que ese `valid_from` es una modificación del DOF y no la
    entrada en vigor del documento. Con `reform_note = NULL` da falso, que es
    lo correcto: sin nota no consta reforma.
    """
    fecha_dof = sa.func.to_char(LegalRule.valid_from, FORMATO_FECHA_DOF)
    return sa.func.coalesce(LegalRule.reform_note.contains(fecha_dof), sa.false())


#: Fila de `_olas`: documento, kind, vigencia del documento, día, cuántas
#: normas citan ese día, cuántas no, y la muestra de cada grupo.
FilaOla = tuple[str, str, date | None, date, int, int, list[str] | None, list[str] | None]


def _olas(session: Session) -> list[FilaOla]:
    """Normas agrupadas por (documento, día en que empiezan a regir).

    Por documento y no sólo por día: cuando entre RGCE 2026, su 2026-01-01 no
    puede sumarse a lo que otro documento hiciera ese día. Y cada grupo se
    parte en dos —las que citan ese día en su nota y las que no— porque un
    mismo día puede tener las dos cosas (la Ley Aduanera del 1995-12-15: 54
    artículos de la publicación original y uno derogado ese día).

    `array_agg` con `ORDER BY` para que la muestra sea estable entre llamadas.
    """
    cita = _cita_su_fecha()
    orden = aggregate_order_by(LegalRule.rule_number, LegalRule.rule_number)
    return [
        tuple(fila)  # type: ignore[misc]
        for fila in session.execute(
            sa.select(
                LegalDocument.short_name,
                LegalDocument.kind,
                LegalDocument.valid_from,
                LegalRule.valid_from,
                sa.func.count().filter(cita),
                sa.func.count().filter(sa.not_(cita)),
                sa.func.array_agg(orden).filter(cita),
                sa.func.array_agg(orden).filter(sa.not_(cita)),
            )
            .select_from(LegalRule)
            .join(LegalDocument, LegalDocument.id == LegalRule.legal_document_id)
            .group_by(
                LegalDocument.short_name,
                LegalDocument.kind,
                LegalDocument.valid_from,
                LegalRule.valid_from,
            )
        ).all()
    ]


def _clasificar_olas(
    filas: list[FilaOla],
) -> tuple[list[OlaDeReforma], list[EntradaEnVigor]]:
    """Separa reforma de entrada en vigor. Sin tope: el tope lo pone quien llama.

    Una fila puede producir las dos cosas a la vez. Lo que no hace nunca es
    contar como reformada una norma cuya nota no cita ese día.
    """
    reformas: list[OlaDeReforma] = []
    entradas: list[EntradaEnVigor] = []
    for documento, kind, vigencia_doc, dia, citan, no_citan, m_citan, m_no in filas:
        if citan:
            reformas.append(
                OlaDeReforma(
                    fecha=dia,
                    documento=documento,
                    kind=kind,
                    normas=citan,
                    muestra=list((m_citan or [])[:MUESTRA_POR_OLA]),
                )
            )
        if no_citan:
            entradas.append(
                EntradaEnVigor(
                    fecha=dia,
                    documento=documento,
                    kind=kind,
                    normas=no_citan,
                    tipo="DOCUMENTO_COMPLETO" if dia == vigencia_doc else "SIN_REFORMA_REGISTRADA",
                    muestra=list((m_no or [])[:MUESTRA_POR_OLA]),
                )
            )

    def _reciente(x: OlaDeReforma | EntradaEnVigor) -> tuple[int, str]:
        return (-x.fecha.toordinal(), x.documento)

    reformas.sort(key=_reciente)
    entradas.sort(key=_reciente)
    return reformas, entradas


def _fuera_de_vigencia(session: Session) -> list[NormaFueraDeVigencia]:
    filas = session.execute(
        sa.select(
            LegalRule.rule_number,
            LegalDocument.short_name,
            LegalRule.valid_from,
            LegalRule.valid_to,
            LegalRule.heading_text,
        )
        .select_from(LegalRule)
        .join(LegalDocument, LegalDocument.id == LegalRule.legal_document_id)
        .where(LegalRule.valid_to.isnot(None))
        .order_by(LegalRule.valid_to.desc(), LegalRule.rule_number)
        .limit(TOPE_FUERA_DE_VIGENCIA)
    ).all()

    return [
        NormaFueraDeVigencia(
            rule_number=numero,
            documento=documento,
            valid_from=desde,
            valid_to=hasta,
            encabezado=encabezado,
        )
        for numero, documento, desde, hasta, encabezado in filas
    ]


def _impacto(session: Session) -> ImpactoEnDecisiones:
    """Decisiones que citaron una norma que no estaba vigente en su fecha.

    Es la única afirmación de impacto que se puede sostener: exige que la
    decisión haya guardado `legal_rule_ids`. Las que no lo hicieron no se
    cuentan como limpias — se cuentan como no trazables.
    """
    citadas = sa.func.coalesce(sa.func.cardinality(ClassificationDecision.legal_rule_ids), 0) > 0

    total = session.scalar(sa.select(sa.func.count()).select_from(ClassificationDecision)) or 0
    con_normas = (
        session.scalar(
            sa.select(sa.func.count()).select_from(ClassificationDecision).where(citadas)
        )
        or 0
    )

    # Una decisión está afectada si EXISTE una norma citada que no estuviera
    # vigente en su `operation_date`. `exists` y no `join`, para no contar dos
    # veces la misma decisión cuando cita varias normas caducas.
    caduca = sa.exists(
        sa.select(sa.literal(1))
        .select_from(LegalRule)
        .where(
            LegalRule.id == sa.any_(ClassificationDecision.legal_rule_ids),
            sa.not_(
                sa.and_(
                    LegalRule.valid_from <= ClassificationDecision.operation_date,
                    sa.or_(
                        LegalRule.valid_to.is_(None),
                        LegalRule.valid_to >= ClassificationDecision.operation_date,
                    ),
                )
            ),
        )
    )
    afectadas = (
        session.scalar(
            sa.select(sa.func.count()).select_from(ClassificationDecision).where(citadas, caduca)
        )
        or 0
    )

    return ImpactoEnDecisiones(
        decisiones=total,
        con_normas_citadas=con_normas,
        sin_normas_citadas=total - con_normas,
        afectadas=afectadas,
        trazable=con_normas > 0,
    )


@router.get("", summary="Vigilancia normativa")
def centinela(
    session: SessionDep,
    fecha: Annotated[
        date | None,
        Query(description="Fecha de referencia para la vigencia (§14). Por omisión, hoy."),
    ] = None,
) -> Sentinel:
    """Todo el estado de la vigilancia en una respuesta."""
    # `today()` sin zona a propósito: es una fecha de vigencia, no un instante.
    on_date = fecha or date.today()

    total = session.scalar(sa.select(sa.func.count()).select_from(LegalRule)) or 0
    vigentes = (
        session.scalar(sa.select(sa.func.count()).select_from(LegalRule).where(_vigentes(on_date)))
        or 0
    )
    caducas = (
        session.scalar(
            sa.select(sa.func.count()).select_from(LegalRule).where(LegalRule.valid_to.isnot(None))
        )
        or 0
    )
    eventos = session.scalar(sa.select(sa.func.count()).select_from(RegulatoryEvent)) or 0

    documentos = _corpus(session)
    reformas, entradas = _clasificar_olas(_olas(session))

    return Sentinel(
        fecha=on_date,
        corpus=documentos,
        normas_totales=total,
        vigentes_en_fecha=vigentes,
        fuera_de_vigencia_total=caducas,
        reformas=reformas[:TOPE_REFORMAS],
        total_olas=len(reformas),
        entradas_en_vigor=entradas[:TOPE_ENTRADAS],
        total_entradas_en_vigor=len(entradas),
        fuera_de_vigencia=_fuera_de_vigencia(session),
        eventos_dof=eventos,
        vigilancia_automatica=eventos > 0,
        impacto=_impacto(session),
        corpus_sintetico=sum(1 for d in documentos if not d.es_fuente_oficial),
    )
