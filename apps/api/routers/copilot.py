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

LA BÚSQUEDA DE HOY NO ES SEMÁNTICA, Y SE DECLARA

Los 366 chunks están sin vectorizar porque no hay `OPENAI_API_KEY`. Sin
vector, `PostgresChunkStore` busca por coincidencia de término y ordena por
lo más vigente primero. Funciona —así se fundamentan hoy las
clasificaciones— pero no es lo mismo que buscar por significado, y
presentarlo como si lo fuera sería vender una capacidad que no está puesta.
`modo_busqueda` lo dice en cada respuesta.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Final

import sqlalchemy as sa
from database.models.regulatory import LegalChunkRecord
from database.repositories.chunks import PostgresChunkStore
from fastapi import APIRouter
from pydantic import BaseModel, Field
from rag import recuperar, terminos_de_consulta
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

#: Cómo se buscó. Hoy sólo puede ser el primero: ningún consumidor del RAG
#: pasa un embedder todavía, así que tener el corpus vectorizado no cambia
#: cómo se busca. El segundo existe para cuando se conecte el adaptador — y
#: hasta entonces no se emite, porque anunciarlo sería vender la capacidad sin
#: haberla puesto.
MODO_TERMINO = "TERMINO_Y_VIGENCIA"
MODO_SEMANTICO = "SEMANTICA"


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
    """¿Esta consulta se resolvió por significado? Hoy, nunca.

    No es lo mismo que «el corpus tiene vectores»: eso es `chunks_vectorizados`.
    Falta el adaptador que convierta la pregunta en vector, y conectarlo tiene
    coste por consulta — es decisión de Persona 1, no efecto de que alguien
    corriera el backfill.
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


def _reordenar(pasajes: list[Pasaje]) -> list[Pasaje]:
    """Primero los que casan más términos; a igualdad, lo más vigente.

    El almacén ordena sólo por vigencia porque sin vector es el desempate
    menos arbitrario. Pero deja que un pasaje que casa un término adelante a
    uno que casa cuatro, y entonces el orden se lee como pertinencia sin
    serlo. Reordenar aquí no toca el repositorio ni inventa un ranking: usa
    los términos que el propio buscador empleó.
    """
    return sorted(
        pasajes,
        key=lambda p: (-len(p.terminos_coincidentes), -p.valid_from.toordinal()),
    )


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


@router.post("/consultas", summary="Pregunta al corpus jurídico")
def consultar(consulta: Consulta, session: SessionDep) -> Respuesta:
    """Recupera los pasajes vigentes que hablan de la pregunta.

    No redacta una respuesta: devuelve la norma. Ver el módulo para el porqué.
    """
    # `date.today()` sin zona a propósito: es una fecha de vigencia, no un
    # instante.
    on_date = consulta.fecha or date.today()
    totales, vectorizados = _cobertura(session)

    # `embedder=None`: sin OPENAI_API_KEY no hay con qué vectorizar la
    # pregunta. `PostgresChunkStore` cae entonces a término + vigencia, que es
    # exactamente lo que `modo_busqueda` declara. Cuando haya llave, aquí entra
    # el embedder y el resto del camino no cambia.
    terminos = terminos_de_consulta(consulta.pregunta)

    # Se piden más de los que se van a devolver para poder reordenar por
    # cuántos términos casa cada uno. Ver FACTOR_CANDIDATOS.
    recuperacion = recuperar(
        consulta.pregunta,
        on_date=on_date,
        store=PostgresChunkStore(session),
        embedder=None,
        limit=consulta.limite * FACTOR_CANDIDATOS,
    )

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
            terminos_coincidentes=_coincidencias(c.text, terminos),
        )
        for c in recuperacion.chunks
    ]
    pasajes = _reordenar(pasajes)[: consulta.limite]

    return Respuesta(
        pregunta=consulta.pregunta,
        fecha=on_date,
        pasajes=pasajes,
        hay_fundamento=recuperacion.hay_fundamento,
        sin_evidencia=None if recuperacion.hay_fundamento else recuperacion.sin_evidencia(),
        descartados_por_vigencia=recuperacion.descartados_por_vigencia,
        descartados_por_origen=recuperacion.descartados_por_origen,
        terminos_buscados=list(terminos),
        # `embedder=None` arriba: la búsqueda fue por término, punto. El modo
        # dice lo que pasó, no lo que el corpus permitiría.
        modo_busqueda=MODO_TERMINO,
        busqueda_semantica_disponible=False,
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
        modo_busqueda=MODO_TERMINO,
        busqueda_semantica_disponible=False,
        chunks_vectorizados=vectorizados,
        chunks_totales=totales,
    )
