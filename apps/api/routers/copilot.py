"""Copilot (§32) — consulta al corpus jurídico, con vigencia y procedencia.

LO QUE ESTE COPILOT NO HACE: REDACTAR LA RESPUESTA

Un asistente jurídico que parafrasea la ley es la forma más eficiente de
producir una cita inventada. El maestro lo dice justo antes del §32 —«nunca
inventar citas»— y la manera de cumplirlo no es pedirle al modelo que se
porte bien: es no ponerlo en posición de inventar. Aquí se devuelven los
PASAJES, con su artículo, su vigencia, su procedencia y su hash. Quien lee
saca la conclusión sobre el texto de la norma, no sobre un resumen de ella.

El día que haya llave y se quiera redactar, la síntesis se apoya sobre esto
mismo: los pasajes ya recuperados son el fundamento, y lo que no salga de
ellos no se escribe. No hay que rehacer nada.

QUÉ SÍ HACE, Y QUE NO ES POCO

Filtra por fecha de operación (§14) y por procedencia (§8). Una consulta
sobre una operación de 2024 no puede devolver una norma de 2026 por muy
pertinente que parezca, y un chunk `SYNTHETIC` no fundamenta nada aunque
esté completo. Las dos cosas las hace `rag.recuperar`; este router las
expone y —sobre todo— DICE cuántos candidatos tiró por cada motivo. Un
buscador que descarta en silencio parece que no encontró nada.

CÓMO SE BUSCÓ SE DECLARA EN CADA RESPUESTA

El corpus ya está vectorizado (Persona 1 corrió el backfill el 9 de
septiembre), así que la consulta se vectoriza y se busca por significado.
Pero eso puede no ocurrir: sin llave, sin cuota o con un 429, `rag.embedder`
degrada a búsqueda por término y vigencia en vez de tumbar la petición.

`modo_busqueda` dice cuál de las dos pasó DE VERDAD, no de cuál es capaz el
corpus. La distinción tiene una historia: la primera versión de este router
lo derivaba de si había vectores en la base, y cuando el backfill terminó
empezó a anunciar SEMANTICA mientras seguía buscando por palabra. Un módulo
cuya tesis es no anunciar estados falsos no puede permitirse eso.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Final

import sqlalchemy as sa
from database.models.regulatory import LegalChunkRecord, LegalDocument
from database.repositories.chunks import PostgresChunkStore
from fastapi import APIRouter
from pydantic import BaseModel, Field
from rag import (
    MODO_SEMANTICO,
    MODO_TERMINO,
    ORIGENES_QUE_FUNDAMENTAN,
    EmbedderDegradable,
    embedder_opcional,
    recuperar,
    terminos_de_consulta,
)
from rag.retrieval import LIMITE_POR_DEFECTO

from apps.api.db import SessionDep

router = APIRouter(prefix="/copilot", tags=["copilot"])

#: Tope duro. Más pasajes no responden mejor: diluyen y alargan la lectura.
LIMITE_MAXIMO = 20

#: Cuántos candidatos se piden para poder reordenar. El almacén ordena por
#: vigencia —lo menos arbitrario cuando no hay vector—, pero eso deja que un
#: pasaje que casa 1 de 4 términos adelante a uno que casa los 4. Se piden más
#: y se reordenan aquí. Comprobado contra el corpus real: «obligaciones del
#: importador en el valor en aduana» devolvía notas de capítulo de la LIGIE
#: porque contenían «valor», y nada más.
FACTOR_CANDIDATOS: Final = 4


class Consulta(BaseModel):
    """Una pregunta al corpus, situada en el tiempo."""

    pregunta: str = Field(min_length=3, max_length=1000)
    fecha: date | None = Field(
        default=None,
        description=(
            "Fecha de la operación. Decide qué normas podían citarse (§14). "
            "Por omisión, hoy — que es lo correcto para una consulta general "
            "y lo INCORRECTO para revisar una operación pasada."
        ),
    )
    limite: int = Field(default=LIMITE_POR_DEFECTO, ge=1, le=LIMITE_MAXIMO)


class Pasaje(BaseModel):
    """Un fragmento de norma, tal como está en el corpus.

    Se devuelve el texto, no un resumen: resumir una norma es donde se pierde
    la condición que hacía que no aplicara.
    """

    documento: str
    articulo: str | None = None
    encabezado: str | None = None
    texto: str
    cita: str
    """La cita formada por el propio chunk. Nunca se compone aquí a mano."""
    valid_from: date
    valid_to: date | None = None
    data_origin: str
    puede_fundamentar: bool
    """`False` = sirve para orientarse, no para sostener nada ante nadie."""
    url: str | None = None
    content_hash: str | None = None
    distancia: float | None = None
    """Distancia del coseno a la pregunta. `None` si se buscó por término.

    Se enseña como dato, no como veredicto: medido el 23-sep contra el corpus
    cargado, las preguntas respondibles y las que no tienen corpus se SOLAPAN
    en este número.
    """

    terminos_coincidentes: list[str] = Field(default_factory=list)
    """Cuáles de los términos buscados aparecen de verdad en este pasaje.

    Es la calidad del acierto, a la vista. Sin vectores la búsqueda casa con
    que UNO de los términos aparezca, así que un pasaje puede salir por
    contener «valor» y nada más. Enseñar cuáles casó evita que el orden se
    lea como pertinencia."""


class Respuesta(BaseModel):
    """Lo que el corpus tiene sobre la pregunta, y qué se puede hacer con ello."""

    pregunta: str
    fecha: date

    pasajes: list[Pasaje] = Field(default_factory=list)

    hay_fundamento: bool = False
    """¿Hay al menos un pasaje que pueda sostener una afirmación jurídica?"""

    sin_evidencia: str | None = None
    """El mensaje literal cuando no hay con qué responder.

    Se devuelve tal cual, sin adornar: «no tengo evidencia» es una respuesta
    correcta, y disfrazarla de respuesta parcial no lo sería.
    """

    descartados_por_vigencia: int = 0
    """Coincidían con la pregunta, pero no regían esa fecha."""
    descartados_por_origen: int = 0
    """Regían, pero no pueden fundamentar: fixtures o fuentes no oficiales."""

    terminos_buscados: list[str] = Field(default_factory=list)
    """Con qué se buscó realmente. Las palabras vacías no cuentan."""

    modo_busqueda: str = MODO_TERMINO
    """Cómo se buscó DE VERDAD en esta consulta, no de qué es capaz el corpus.

    Hoy siempre `TERMINO_Y_VIGENCIA`: ningún consumidor del RAG pasa todavía
    un embedder, así que aunque los chunks estén vectorizados la búsqueda
    sigue siendo por coincidencia de palabra. Derivarlo del estado del corpus
    —como hacía la primera versión de este router— anunciaba búsqueda
    semántica mientras se hacía la otra: exactamente la capacidad vendida y
    no puesta que este módulo dice evitar.
    """

    busqueda_semantica_disponible: bool = False
    """¿ESTA consulta se resolvió por significado?

    No es lo mismo que «el corpus tiene vectores» —eso es
    `chunks_vectorizados`— ni que «hay llave configurada». Es si se llegó a
    vectorizar la pregunta y el proveedor respondió.
    """

    degradado_por: str | None = None
    """Por qué se buscó por término teniendo el corpus vectorizado.

    `None` cuando no hubo degradación. Degradar en silencio sería tan malo
    como fallar: el resultado saldría peor sin que nadie pudiera saber por qué
    (Persona 1, 2026-09-09)."""

    corpus_consultado: list[str] = Field(default_factory=list)
    """Los instrumentos que regían ese día y en los que SE BUSCÓ.

    Es la respuesta honesta a «¿por qué me devolviste la Ley Aduanera cuando
    pregunté por PROSEC?»: porque el decreto PROSEC, los cupos y el Anexo
    2.2.1 no están cargados, y la búsqueda semántica siempre devuelve lo más
    cercano de lo que hay. Sin esta lista, ocho pasajes citables y vigentes
    parecen una respuesta a cualquier cosa que se pregunte.

    `hay_fundamento` no cubre esto y no pretende hacerlo: dice que los pasajes
    PUEDEN fundamentar —vigencia y procedencia—, no que respondan la pregunta.
    Son dos cosas distintas y hacían falta las dos.
    """

    chunks_vectorizados: int = 0
    """Cuántos chunks ya tienen vector. Los consuma alguien o no."""
    chunks_totales: int = 0

    redacta_respuesta: bool = False
    """Siempre `false`, y es una decisión, no una carencia.

    Parafrasear la ley es como se producen las citas inventadas. Se devuelven
    los pasajes para que quien lee saque la conclusión sobre el texto de la
    norma, no sobre un resumen de ella.
    """


def _coincidencias(texto: str, terminos: tuple[str, ...]) -> list[str]:
    """Cuáles de los términos buscados aparecen de verdad en el pasaje.

    Misma comparación que hace el almacén —`ilike`, o sea sin distinguir
    mayúsculas— para que la cifra que se enseña sea la que produjo el acierto
    y no otra parecida.
    """
    bajo = texto.lower()
    return [t for t in terminos if t in bajo]


def _reordenar(pasajes: list[Pasaje], *, uso_vectores: bool) -> list[Pasaje]:
    """Primero los que casan más términos; a igualdad, lo más vigente.

    SÓLO CUANDO SE BUSCÓ POR TÉRMINO. Con vectores, el almacén ya ordenó por
    distancia coseno y ese orden ES la pertinencia: reordenar por solapamiento
    de palabras lo destruye.

    Lo comprobé contra el corpus real y la diferencia es total. «mercancía que
    se deteriora si permanece almacenada mucho tiempo», por coseno, devuelve
    los artículos 34, 27 y 25 —conservación y depósito ante la aduana, que es
    la respuesta correcta—. Reordenando por términos salían el 119, 135-C y 94,
    que sólo comparten las palabras «mercancía» y «permanece». El vector
    entiende «se deteriora»; contar palabras, no.

    Sin vector sigue haciendo falta: el almacén ordena por vigencia, que es el
    desempate menos arbitrario pero deja que un pasaje que casa un término
    adelante a uno que casa cuatro.
    """
    if uso_vectores:
        return pasajes
    return sorted(
        pasajes,
        key=lambda p: (-len(p.terminos_coincidentes), -p.valid_from.toordinal()),
    )


def _porque_no_vectores(embedder: EmbedderDegradable | None) -> str:
    """Por qué esta consulta no usó vectores. Siempre hay una razón que dar."""
    if embedder is None:
        return "no hay proveedor de embeddings configurado"
    if embedder.motivo_degradacion:
        return f"el proveedor falló y se siguió por término: {embedder.motivo_degradacion}"
    return "no se intentó vectorizar la consulta"


def _cobertura(session: SessionDep) -> tuple[int, int]:
    """Cuántos chunks hay y cuántos están vectorizados."""
    totales = session.scalar(sa.select(sa.func.count()).select_from(LegalChunkRecord)) or 0
    vectorizados = (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(LegalChunkRecord)
            .where(LegalChunkRecord.embedding.is_not(None))
        )
        or 0
    )
    return totales, vectorizados


def _corpus_consultado(session: SessionDep, on_date: date) -> list[str]:
    """Qué instrumentos regían ese día y tenían pasajes donde buscar.

    Se lee de la base y no de una lista escrita aquí: el día que se cargue el
    Anexo 2.2.1 aparece solo. Y sólo los que pueden fundamentar, que son
    exactamente los que la recuperación admite — enseñar un instrumento que el
    buscador descarta sería peor que no enseñar nada.
    """
    filas = session.scalars(
        sa.select(LegalDocument.title)
        .join(LegalChunkRecord, LegalChunkRecord.legal_document_id == LegalDocument.id)
        .where(LegalChunkRecord.data_origin.in_(ORIGENES_QUE_FUNDAMENTAN))
        .where(LegalChunkRecord.valid_from <= on_date)
        .where(sa.or_(LegalChunkRecord.valid_to.is_(None), LegalChunkRecord.valid_to >= on_date))
        .distinct()
        .order_by(LegalDocument.title)
    ).all()
    return list(filas)


@router.post("/consultas", summary="Pregunta al corpus jurídico")
def consultar(consulta: Consulta, session: SessionDep) -> Respuesta:
    """Recupera los pasajes vigentes que hablan de la pregunta.

    No redacta una respuesta: devuelve la norma. Ver el módulo para el porqué.
    """
    # `date.today()` sin zona a propósito: es una fecha de vigencia, no un
    # instante.
    on_date = consulta.fecha or date.today()
    totales, vectorizados = _cobertura(session)

    terminos = terminos_de_consulta(consulta.pregunta)

    # El embedder puede ser `None` (sin proveedor) o degradarse a mitad (429,
    # timeout). En los dos casos `recuperar` sigue por término y vigencia: una
    # consulta no se cae porque el proveedor de vectores esté caído.
    embedder = embedder_opcional()

    # Se sobre-piden candidatos SÓLO para poder reordenar por términos. Con
    # vectores no se reordena, así que pedir de más sería traer resultados
    # peores por coseno para luego tirarlos. Ver FACTOR_CANDIDATOS.
    #
    # Se decide antes de saber si el embedder respondió: si degrada a mitad,
    # se habrá pedido de menos y el reordenamiento trabajará sobre menos
    # candidatos. Es el precio de no llamar dos veces al almacén, y afecta al
    # orden, nunca a si un pasaje puede fundamentar.
    posible_vector = embedder is not None
    candidatos = consulta.limite if posible_vector else consulta.limite * FACTOR_CANDIDATOS

    recuperacion = recuperar(
        consulta.pregunta,
        on_date=on_date,
        store=PostgresChunkStore(session),
        embedder=embedder,
        limit=candidatos,
    )

    # Se pregunta DESPUÉS de recuperar: hasta que no se intentó vectorizar no
    # se sabe si el proveedor respondió.
    uso_vectores = embedder is not None and embedder.uso_vectores

    pasajes = [
        Pasaje(
            documento=c.document,
            articulo=c.article,
            encabezado=c.heading,
            texto=c.text,
            cita=c.cita(),
            valid_from=c.valid_from,
            valid_to=c.valid_to,
            data_origin=c.data_origin,
            puede_fundamentar=c.puede_fundamentar,
            url=c.url,
            content_hash=c.content_hash,
            distancia=c.distancia,
            terminos_coincidentes=_coincidencias(c.text, terminos),
        )
        for c in recuperacion.chunks
    ]
    pasajes = _reordenar(pasajes, uso_vectores=uso_vectores)[: consulta.limite]

    return Respuesta(
        pregunta=consulta.pregunta,
        fecha=on_date,
        pasajes=pasajes,
        hay_fundamento=recuperacion.hay_fundamento,
        sin_evidencia=None if recuperacion.hay_fundamento else recuperacion.sin_evidencia(),
        descartados_por_vigencia=recuperacion.descartados_por_vigencia,
        descartados_por_origen=recuperacion.descartados_por_origen,
        corpus_consultado=_corpus_consultado(session, on_date),
        terminos_buscados=list(terminos),
        # El modo dice lo que pasó, no lo que el corpus permitiría.
        modo_busqueda=MODO_SEMANTICO if uso_vectores else MODO_TERMINO,
        busqueda_semantica_disponible=uso_vectores,
        degradado_por=None if uso_vectores else _porque_no_vectores(embedder),
        chunks_vectorizados=vectorizados,
        chunks_totales=totales,
        redacta_respuesta=False,
    )


@router.get("/cobertura", summary="Qué corpus hay detrás del Copilot")
def cobertura(
    session: SessionDep,
    fecha: Annotated[
        date | None, Field(description="Vigencia de referencia. Por omisión, hoy.")
    ] = None,
) -> Respuesta:
    """El estado del corpus sin hacer una consulta.

    Sirve para que la pantalla pueda decir con qué se va a buscar ANTES de que
    alguien escriba la primera pregunta.
    """
    on_date = fecha or date.today()
    totales, vectorizados = _cobertura(session)
    return Respuesta(
        pregunta="",
        fecha=on_date,
        # Aquí es donde más falta hacía: esta ruta existe para decir con qué se
        # va a buscar, y contestaba con dos números sin nombrar un instrumento.
        corpus_consultado=_corpus_consultado(session, on_date),
        modo_busqueda=MODO_TERMINO,
        busqueda_semantica_disponible=False,
        chunks_vectorizados=vectorizados,
        chunks_totales=totales,
    )
