"""Bandeja de revisión humana (§39).

Las correcciones humanas son el activo más valioso del sistema: son lo único
que ninguna otra parte genera, y lo que permite medir «fraction accuracy» y
«human review rate» del §39.

LA CORRECCIÓN NO SOBRESCRIBE A LA MÁQUINA

Medir la precisión exige conservar las dos respuestas: la del motor y la de
la persona. Si la revisión editara la decisión original, el numerador de esa
métrica desaparecería — y con él la única forma de saber si el sistema está
mejorando.

Por eso una revisión crea una fila NUEVA con `data_origin = HUMAN_VALIDATED`,
y la original sólo deja de estar pendiente. Ambas comparten `product_dna_id`,
que es lo que permite emparejarlas al evaluar.

Es el mismo criterio que Persona 1 aplicó a `shadow_reviews`: una revisión es
un evento, no un atributo.

UN CASO SE REVISA UNA SOLA VEZ, Y EL VEREDICTO DICE QUÉ REVISÓ

Cada veredicto guarda `reviews_decision_id`: la decisión de máquina que
revisa. Antes no lo guardaba y la métrica emparejaba por DNA y tiempo; con un
DNA de tres fechas de operación, el veredicto sobre el caso de 2024 se
comparaba contra la decisión de 2026 (Persona 1, opción 1, 14-sep).

«Ya revisada» significa «existe un veredicto que apunta a esta decisión».
Tres capas, de fuera hacia dentro:

    1. la aplicación comprueba si ya hay veredicto → 409
    2. la original se lee con SELECT … FOR UPDATE → dos POST simultáneos se
       ordenan y el segundo ya ve el primero
    3. UNIQUE sobre `reviews_decision_id` → si alguien se salta la aplicación,
       decide la base, y su violación también se devuelve como 409

Una decisión resuelta limpia, que nunca estuvo en la bandeja, SÍ puede
revisarse: es lo que hace falta para muestrear lo que la bandeja deja pasar.

LA BANDEJA DICE POR QUÉ ESTÁ CADA CASO

No todos los pendientes piden lo mismo, y hasta ahora se veían iguales. Desde
que la RGI 3 c) marca sus resoluciones (PR #69 de Persona 1) conviven tres
especies:

    · no se pudo resolver — falta información
    · se resolvió y aun así hay que mirarlo
    · se llegó al desempate de último recurso, que aplica la regla
      correctamente y no distingue nada: entre una computadora y un monitor
      elige el monitor porque 8528 va después de 8471

Un revisor que no distingue la tercera de la primera no sabe qué le están
pidiendo: en una falta información, en la otra sobra una respuesta que nadie
debería firmar tal cual.

`causas` es una LISTA, no un valor único, y no lleva severidad. Elegir una
sola exigiría un orden de precedencia que el dato no sostiene —un caso puede
carecer de información Y haber llegado al desempate— y ordenarlas por gravedad
sería una opinión disfrazada de dato. Se nombran; el revisor decide.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Final, Literal

import sqlalchemy as sa
from core.rgi_engine import ClassificationContext, ProductFact
from core.rgi_engine.rules import la_ficha_dice
from database.models import (
    ClassificationDecision,
    NomenclatureSynonym,
    Product,
    ProductDna,
    TariffHeading,
)
from database.repositories import save_classification
from database.repositories.preguntas import pendientes as pendientes_vigentes
from database.repositories.preguntas import productos_que_preguntaban
from database.repositories.tariff import TariffCatalogRepository
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field
from schemas.intelligence import ClassificationDecisionRead
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.clasificacion import clasificar_borrador
from apps.api.db import SessionDep, get_sessionmaker
from apps.api.dna import cargar_borrador, version_vigente
from apps.api.logging import get_logger

log = get_logger("apps.api.review")

router = APIRouter(prefix="/review", tags=["review"])

LIMITE_MAXIMO = 200

#: Lo que puede decir quien revisa.
#:
#: `FALTA_INFORMACION` no es una no-respuesta, y no es lo mismo que no revisar:
#: la persona MIRÓ la ficha y dice que con lo que trae no se puede determinar
#: la fracción, nombrando el dato que falta.
#:
#: Hasta hoy no cabía en el tipo. En el dictamen del 5-oct, César escribió en
#: tres casos «NO DETERMINABLE, pidan el dato, no inventen una fracción», y las
#: dos únicas formas de guardarlo eran `CORRIGE` —que exige una fracción que él
#: no dio, y que habría que inventar— o no guardarlo. Inventarla es justo lo
#: que prohíbe la regla 2; no guardarlo tira el único dato que nadie más
#: produce.
Veredicto = Literal["CONFIRMA", "CORRIGE", "FALTA_INFORMACION"]

#: La regla de desempate de último recurso: «la última por orden de
#: numeración». Aplica correctamente y no distingue nada.
REGLA_DESEMPATE = "RGI-3c"

#: Por qué un caso está en la bandeja. Sin severidad y sin precedencia: son
#: causas concurrentes, no niveles.
CAUSAS: Final[dict[str, str]] = {
    "SIN_INFORMACION": (
        "El motor no pudo resolver: falta información del producto. "
        "Lo que se pide es completar el dato, no juzgar una fracción."
    ),
    "DESEMPATE_POR_NUMERACION": (
        "Se llegó a la RGI 3 c), que elige la última partida por orden de "
        "numeración. Aplica la regla correctamente y no distingue nada: entre "
        "una computadora y un monitor elegiría el monitor porque 8528 va "
        "después de 8471."
    ),
    "SIN_FRACCION_PROPUESTA": (
        "No hay fracción que confirmar. Revisar aquí es proponerla, no validar la del motor."
    ),
    "RESUELTA_PERO_MARCADA": (
        "El motor resolvió y aun así pidió revisión. La fracción propuesta es "
        "un punto de partida, no una conclusión."
    ),
}


#: La constraint que garantiza en la base un solo veredicto por decisión.
UNICO_VEREDICTO: Final = "uq_classification_decisions_reviews_decision_id"


def _ya_revisada(session: SessionDep, decision_id: uuid.UUID) -> bool:
    """¿Hay un veredicto que apunte a esta decisión?"""
    return (
        session.scalar(
            sa.select(ClassificationDecision.id)
            .where(ClassificationDecision.reviews_decision_id == decision_id)
            .limit(1)
        )
        is not None
    )


def _es_veredicto_duplicado(exc: IntegrityError) -> bool:
    """¿La violación es la del UNIQUE de veredictos, y no otra?

    Se mira el nombre de la constraint: disfrazar de 409 una violación
    distinta —el CHECK, una FK— escondería un fallo real detrás de un «ya
    estaba revisada».
    """
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None) == UNICO_VEREDICTO


def _normalizar(rule_id: str) -> str:
    """`RGI-3c`, `RGI3C` y `rgi 3 c` son la misma regla.

    El seed antiguo escribió `RGI1` sin guion y la traza del motor escribe
    `RGI-1`. Comparar en crudo dejaría casos sin causa según quién los
    escribiera, y un caso sin causa es justo lo que esta pantalla viene a
    eliminar.
    """
    return "".join(c for c in rule_id if c.isalnum()).upper()


def _causas(fila: ClassificationDecision) -> list[str]:
    """Por qué está este caso en la bandeja. Puede haber más de una razón."""
    encontradas: list[str] = []

    if fila.status == "INSUFFICIENT_INFORMATION":
        encontradas.append("SIN_INFORMACION")

    camino = {_normalizar(r) for r in (fila.rgi_path or [])}
    if _normalizar(REGLA_DESEMPATE) in camino:
        encontradas.append("DESEMPATE_POR_NUMERACION")

    if fila.fraction_code is None:
        encontradas.append("SIN_FRACCION_PROPUESTA")
    elif not encontradas:
        # Con fracción y sin ninguna otra causa, lo único que consta es que el
        # motor pidió revisión. Decirlo es mejor que dejar el caso mudo.
        encontradas.append("RESUELTA_PERO_MARCADA")

    return encontradas


class PendienteRead(ClassificationDecisionRead):
    """Una decisión esperando a una persona, con contexto para decidir."""

    producto: str | None = None
    """Nombre comercial, para no tener que abrir otra pantalla."""
    sku: str | None = None
    pasos_traza: int = 0
    """Cuántas reglas se evaluaron. Cero significa que no consta el
    razonamiento, y eso cambia cuánto puede fiarse quien revisa."""

    causas: list[str] = Field(default_factory=list)
    """Por qué está aquí. Lista, no valor único: las causas concurren.

    Vacía nunca debería estar — si lo está, el caso llegó a la bandeja por un
    camino que esta pantalla no sabe nombrar, y eso también es información.
    """

    causas_detalle: list[str] = Field(default_factory=list)
    """Qué se le pide al revisor en cada caso, en una frase."""


class RevisionRequest(BaseModel):
    """El veredicto de una persona."""

    veredicto: Veredicto
    reviewer: str = Field(min_length=1, max_length=64)
    """Quién revisa. Una corrección anónima no es auditable."""
    fraction_code: str | None = Field(default=None, max_length=8)
    """La fracción correcta. Obligatoria si se corrige."""
    nico_code: str | None = Field(default=None, pattern=r"^\d{2}$")
    """El NICO, cuando quien revisa lo determina. Dos dígitos, nunca un entero.

    «La fracción de 8 dígitos y el NICO son niveles distintos; no deben
    mezclarse» (César, 5-oct). Son dos decisiones: la fracción sale de las RGI,
    el NICO de la Regla Complementaria y del catálogo de la fracción ya
    elegida. Un `02` sólo significa algo DENTRO de su fracción — el de la
    73121005 y el de la 73051102 no tienen nada que ver.

    Que esté aquí es lo que decide si el trabajo del revisor se conserva. En su
    dictamen del 5-oct César dio NICO en casi todos los casos y el endpoint no
    tenía dónde ponerlo: se habría guardado la fracción y se habría tirado la
    mitad de lo que dijo, sin que nada avisara.

    El patrón de dos dígitos no es cosmético. `2` no es `02`: no empataría con
    ningún código del catálogo y el rechazo habría parecido un NICO inexistente
    en vez de un dígito que falta.
    """
    nota: str | None = None
    """Por qué. Es lo que hace utilizable la corrección para entrenar."""


class RevisionResponse(BaseModel):
    original_id: uuid.UUID
    revision_id: uuid.UUID
    """La fila nueva con el veredicto humano. La original se conserva."""
    veredicto: Veredicto
    fraction_code: str | None = None
    nico_code: str | None = None
    """Se devuelve para que quien lo envió pueda comprobar que se guardó.

    Un campo que se acepta y no se confirma es indistinguible de uno que se
    ignora en silencio.
    """


@router.get("", summary="Decisiones esperando revisión humana")
def pendientes(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = 50,
) -> list[PendienteRead]:
    """La bandeja, de la más antigua a la más reciente.

    Lo más viejo primero a propósito: en una bandeja de trabajo, lo que lleva
    más tiempo esperando es lo que más urge, no lo que acaba de llegar.

    UN CASO POR FICHA, NO UNO POR VEZ QUE SE CLASIFICÓ

    Clasificar el mismo producto otra vez —por una prueba, por un cambio del
    motor, por volver a medir— dejaba una decisión pendiente más. La bandeja
    llegó a tener el mismo producto DIEZ veces mientras los casos que de verdad
    importaban esperaban debajo. Quien revisa perdería la tarde en un solo
    caso, y su veredicto describiría una decisión que el motor ya no toma.

    Es el mismo criterio del #100 en el tablero y del #120 en los hallazgos: el
    estado actual es el último evento, no la unión de todos. Tercera vez que
    aparece el patrón.

    Las decisiones sin ficha pasan una a una: sin `product_dna_id` no hay por
    qué agruparlas, y descartarlas sería perder casos en silencio.

    UN CASO DICTAMINADO NO VUELVE POR RECLASIFICARLO (ADR 0008, 6-oct)

    Medido contra la base compartida: 33 de los 90 casos de la bandeja ya
    tenían veredicto de César. El corpus se reclasificó después, la decisión
    nueva quedó como la más reciente y ningún veredicto apuntaba a ELLA. El
    dictamen es sobre el caso —la ficha—, no sobre una fila concreta del motor.
    """
    # La definición de «pendiente» es UNA y vive en el repositorio (ADR 0008):
    # la misma que decide qué se recalcula al contestar y qué cuenta el script
    # de preguntas. La página se pone aquí, no en la definición.
    filas = session.scalars(
        pendientes_vigentes().order_by(ClassificationDecision.created_at).limit(limit)
    ).all()

    pendientes: list[PendienteRead] = []
    for fila in filas:
        producto = session.get(Product, fila.product_id) if fila.product_id else None
        causas = _causas(fila)
        detalle = PendienteRead.model_validate(fila, from_attributes=True)
        pendientes.append(
            detalle.model_copy(
                update={
                    "producto": producto.commercial_name if producto else None,
                    "sku": producto.sku if producto else None,
                    "pasos_traza": len(fila.rgi_trace or []),
                    "causas": causas,
                    "causas_detalle": [CAUSAS[c] for c in causas],
                }
            )
        )
    return pendientes


# NOTA DE ORDEN: este bloque va ANTES de `POST /{decision_id}` a propósito.
# FastAPI resuelve por orden de declaración, y con la ruta paramétrica delante,
# `/review/vocabulario` entraba por ella e intentaba leer «vocabulario» como un
# UUID. El 422 que devolvía no decía nada de rutas y costaba de ver.


def _desde_cuando_rige_la_tarifa(session: Session) -> date:
    """La vigencia de una respuesta de vocabulario NO es el día que se contestó.

    Lo puse así primero y estaba mal: una respuesta firmada hoy no se aplicaba
    a una operación de marzo, y el motor seguía preguntando lo mismo.

    La regla 5 —no evaluar una operación histórica con regulación posterior—
    protege del FUNDAMENTO, y una equivalencia de vocabulario no fundamenta
    nada: describe qué significan las palabras del texto legal. «Cerámica
    vidriada no es Talavera» era igual de cierto en marzo que hoy, porque el
    texto que lo dice lleva en vigor desde que entró esa versión de la tarifa.

    Así que rige desde que rige lo que describe. Si mañana una reforma cambia
    ese texto, la respuesta vieja se cierra con `valid_to` y se vuelve a
    preguntar sobre el nuevo — que es exactamente lo que debe pasar.
    """
    desde = session.scalar(sa.select(sa.func.min(TariffHeading.valid_from)))
    return desde or date(2022, 1, 1)


class RespuestaVocabulario(BaseModel):
    """Lo que un clasificador contesta a la pregunta de desempate."""

    termino_ficha: str = Field(min_length=2, max_length=120)
    """Como lo dice la ficha: «HFW longitudinal»."""

    termino_tarifa: str = Field(min_length=2, max_length=120)
    """Como lo dice la tarifa: «arco sumergido»."""

    son_lo_mismo: bool
    """La respuesta. El `no` vale tanto como el `sí` y hoy se perdía."""

    reviewer: str = Field(min_length=1, max_length=64)
    """Quién lo contesta. Sin nombre no es criterio, es una opinión anónima."""

    nota: str | None = None
    """Por qué. Lo lee quien audite una decisión que se apoye en esto."""


#: `material = «acero al carbono»` → `acero al carbono`. Etiqueta, igual y
#: comillas de cualquier clase.
_ETIQUETA = re.compile(r"^\s*[^\W\d_]+\s*=\s*")
#: Las comillas se escriben con sus puntos de código para que el linter no
#: avise de caracteres ambiguos: son datos, no texto de programa.
_COMILLAS = "«»\"'" + "\u201c\u201d\u2018\u2019 "


def _solo_el_valor(termino: str) -> str:
    """El valor que la ficha dice, sin la etiqueta con la que se muestra.

    EL PRIMER CLASIFICADOR QUE LO USÓ ESCRIBIÓ LA ETIQUETA (César, 5-oct)

    Contestó `material = "acero al carbono"`, copiando el formato que la propia
    pantalla le enseñaba debajo del campo. Y con eso la respuesta quedaba
    **inerte**: para aplicarse, todas las palabras del término tienen que estar
    en la ficha, y «material» no está — la ficha guarda los VALORES de los
    hechos, no los nombres de los campos.

    Así que su respuesta se guardó firmada, correcta en su razonamiento, y no
    descartaba nada. El motor seguía proponiendo grifería para una tubería.

    Nadie lo habría notado: la pantalla decía «guardado y firmado», la fila
    estaba en la base, y el efecto era cero. Eso es lo peor que puede hacer
    esta función — gastar el minuto de un clasificador sin que se note.

    Se limpia aquí y no sólo en la pantalla porque el endpoint lo llama también
    quien no pasa por ella.
    """
    limpio = _ETIQUETA.sub("", termino).strip().strip(_COMILLAS)
    return limpio.casefold()


#: Cuántos casos se recalculan como máximo al contestar. Clasificar cuesta
#: ~1.5 s medido sobre el corpus, así que 40 son ~60 s de tarea de fondo. Con
#: más, se recalculan los 40 primeros y la respuesta lo dice: quedarse corto en
#: silencio haría creer que el resto ya está al día.
MAX_RECALCULAR: Final = 40


def _recalcular(productos: Sequence[uuid.UUID]) -> None:
    """Vuelve a clasificar esos productos, en una sesión propia.

    LA SESIÓN DE LA PETICIÓN YA ESTÁ CERRADA

    Esto corre DESPUÉS de que la respuesta salga, así que `get_session` ya hizo
    su `rollback()` y devolvió la conexión al pool. Usarla aquí escribiría
    sobre una sesión ajena. Se abre una nueva y se cierra al terminar.

    Un fallo en un producto no detiene los demás: la respuesta ya está firmada
    y guardada, y lo que queda es trabajo derivado. Se registra y se sigue.
    """
    if not productos:
        # Sin nada que hacer no se abre conexión. Abrirla para no usarla gasta
        # una del pool por cada respuesta que no afecta a ningún pendiente.
        return

    sesion = get_sessionmaker()()
    try:
        for product_id in productos:
            try:
                dna_fila = version_vigente(sesion, product_id)
                borrador = cargar_borrador(sesion, product_id)
                if dna_fila is None or borrador is None:
                    continue
                clasificado = clasificar_borrador(
                    sesion,
                    borrador,
                    operation_date=_fecha_de_la_decision(sesion, product_id),
                    trade_flow="IMPORT",
                )
                save_classification(
                    sesion,
                    clasificado.outcome,
                    product_id=product_id,
                    product_dna_id=dna_fila.id,
                    trade_flow="IMPORT",
                )
                sesion.commit()
            except Exception:
                sesion.rollback()
                log.exception("review.recalcular.falla", product_id=str(product_id))
    finally:
        sesion.close()


def _fecha_de_la_decision(session: Session, product_id: uuid.UUID) -> date:
    """La fecha de operación con la que se clasificó antes.

    No `today()`: volver a clasificar con la fecha de hoy evaluaría una
    operación histórica con la tarifa posterior, que es lo que prohíbe la
    regla 5. Se reutiliza la de la última decisión del producto.
    """
    fecha = session.scalar(
        sa.select(ClassificationDecision.operation_date)
        .where(ClassificationDecision.product_id == product_id)
        .order_by(ClassificationDecision.created_at.desc())
        .limit(1)
    )
    return fecha or date.today()


class VocabularioGuardado(BaseModel):
    id: uuid.UUID
    kind: str
    data_origin: str
    recalculando: int = 0
    """Cuántos casos se están volviendo a clasificar con esta respuesta.

    Se devuelve porque es la única forma de que quien contesta sepa que su
    minuto sirvió para algo. Hasta ahora la pantalla decía «guardado» y «para
    que surta efecto hay que reclasificar» — y reclasificar lo hacía una
    persona a mano desde una terminal, así que en la práctica no se
    reclasificaba nunca.
    """
    de_un_total: int = 0
    """Cuántos casos tenían esa pregunta. Mayor que `recalculando` cuando pasan
    de `MAX_RECALCULAR`: el resto se queda para la siguiente pasada, y decirlo
    es mejor que dar por hecho que está al día."""


@router.post(
    "/vocabulario",
    status_code=status.HTTP_201_CREATED,
    summary="Responde una pregunta de desempate y la guarda para siempre",
)
def responder_vocabulario(
    peticion: RespuestaVocabulario, session: SessionDep, tareas: BackgroundTasks
) -> VocabularioGuardado:
    """Convierte un minuto de un clasificador en conocimiento reutilizable.

    POR QUÉ ESTO EXISTE

    Hoy un dictamen resuelve UN caso. Medido sobre el corpus el 2-oct, las 52
    decisiones atascadas se concentran en ocho familias —8528 con 12, 7305 con
    11, 7312 con 8—: la misma duda, una y otra vez, y cada vez el trabajo
    entero otra vez.

    Una respuesta aquí resuelve la familia. La próxima tubería HFW ya no
    pregunta, ni la siguiente, ni las mil siguientes.

    EL «NO» VALE TANTO COMO EL «SÍ»

    `son_lo_mismo = false` no es una no-respuesta: es la que descarta. Que HFW
    NO sea arco sumergido hace imposible la 730511, y eso es una afirmación
    sólida que deja al motor con dos candidatas en vez de nueve. Hasta hoy los
    noes se perdían porque no había dónde guardarlos.

    ENTRA COMO `HUMAN_VALIDATED`, Y ESA COLUMNA ES TODO

    Lo mismo escrito por nosotros sería `SYNTHETIC` — conjetura. Firmado por un
    clasificador es criterio profesional, y es la diferencia entre algo que un
    agente aduanal puede defender y algo que no.
    """
    fila = NomenclatureSynonym(
        commercial_term=_solo_el_valor(peticion.termino_ficha),
        nomenclature_term=peticion.termino_tarifa.strip().casefold(),
        kind="EQUIVALE" if peticion.son_lo_mismo else "EXCLUYE",
        note=peticion.nota,
        answered_by=peticion.reviewer,
        data_origin="HUMAN_VALIDATED",
        valid_from=_desde_cuando_rige_la_tarifa(session),
        source_url=f"respuesta de {peticion.reviewer}",
        source_document="Pregunta de desempate del RGI Engine",
        content_hash=(
            f"vocab:{peticion.termino_ficha}:{peticion.termino_tarifa}:{peticion.son_lo_mismo}"
        ),
        retrieved_at=datetime.now(UTC),
    )
    session.add(fila)
    try:
        session.commit()
    except IntegrityError:
        # Ya estaba contestada. No es un error: es que el bucle funciona.
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "esa pareja ya está contestada; el motor ya no debería preguntarla",
        ) from None

    # CONTESTAR TIENE QUE MOVER ALGO, Y HASTA AHORA NO MOVÍA NADA
    #
    # La respuesta quedaba firmada en la base y las decisiones guardadas
    # seguían siendo las de antes, porque nadie volvía a correr el motor. La
    # pantalla lo decía —«para que surta efecto hay que reclasificar»— y
    # reclasificar lo hacía una persona a mano desde una terminal: en la
    # práctica, no se reclasificaba.
    #
    # Se recalcula DESPUÉS de responder, no durante. Clasificar cuesta ~1.5 s y
    # una familia son veinte casos: hacerlo síncrono dejaría el formulario
    # treinta segundos colgado y quien contesta no sabría si se guardó.
    #
    # El conjunto sale de la TRAZA de los casos pendientes (ADR 0008), no de
    # buscar qué fichas dicen el término.
    afectados = productos_que_preguntaban(session, peticion.termino_tarifa)
    tareas.add_task(_recalcular, afectados[:MAX_RECALCULAR])

    return VocabularioGuardado(
        id=fila.id,
        kind=fila.kind,
        data_origin=fila.data_origin,
        recalculando=len(afectados[:MAX_RECALCULAR]),
        de_un_total=len(afectados),
    )


class RetiroVocabulario(BaseModel):
    """Quién retira una respuesta y por qué. Las dos cosas son obligatorias."""

    reviewer: str = Field(min_length=1, max_length=64)
    """Quién la retira. Normalmente quien la firmó."""
    motivo: str = Field(min_length=5)
    """Por qué estaba mal. Es lo que leerá quien encuentre la fila."""


class VocabularioRetirado(BaseModel):
    id: uuid.UUID
    commercial_term: str
    nomenclature_term: str
    kind: str
    valid_from: date
    valid_to: date
    """Anterior a `valid_from`: la respuesta no rige para ninguna fecha."""


def _esta_retirada(fila: NomenclatureSynonym) -> bool:
    """¿Se retiró? Una vigencia que acaba antes de empezar no rige nunca."""
    return fila.valid_to is not None and fila.valid_to < fila.valid_from


#: Cuántas fichas se enseñan como ejemplo. Bastan para que el número se
#: entienda —«acero» en un cable, una olla y un tubo— sin convertir el aviso en
#: una lista que nadie lee.
EJEMPLOS_DE_ALCANCE: Final = 5


class AlcanceVocabulario(BaseModel):
    """A cuántas fichas alcanzaría una respuesta, ANTES de guardarla."""

    termino_ficha: str
    """El término tal como se guardaría: sin la etiqueta del campo."""
    fichas: int
    """Cuántas fichas vigentes dicen ese término, con la regla del motor."""
    de_un_total: int
    ejemplos: list[str] = Field(default_factory=list)
    """`SKU · descripción` de algunas, para que el número no sea abstracto."""


@router.get(
    "/vocabulario/alcance",
    summary="A cuántas fichas alcanzaría una respuesta de vocabulario",
)
def alcance_vocabulario(
    session: SessionDep,
    termino_ficha: Annotated[str, Query(min_length=2, max_length=120)],
) -> AlcanceVocabulario:
    """Cuántas fichas dicen el término que se está eligiendo.

    POR QUÉ HACÍA FALTA (César, 6-oct)

    César contestó una pregunta sobre un cable eligiendo «acero» como dato de
    la ficha, y el sistema guardó «nada de acero es galvanizado». Quería decir
    «este cable no lo es»; el dato que debió elegir era «sin recubrimiento».
    La pantalla le decía «tu respuesta vale para todas las fichas que digan lo
    mismo», pero no CUÁNTAS eran — y con «acero» eran casi todo el corpus.

    Una respuesta se aplica a cada ficha que diga su término comercial (y en
    cada posición cuyo texto diga la cláusula). Este número es el primer
    factor, que es el que elige quien contesta: cuanto más general el dato, a
    más alcanza.

    LA MISMA REGLA QUE EL MOTOR, NO UNA PARECIDA

    Se pregunta con `la_ficha_dice`, la función con la que el motor decide si
    una respuesta firmada se aplica a una ficha. La ficha se arma como en
    `core.classification.orchestrator.classify_product`: el resumen más los
    VALORES de los hechos. Una copia de la regla ya se desvió una vez.
    """
    termino = _solo_el_valor(termino_ficha)
    productos = session.scalars(
        sa.select(ProductDna.product_id).where(ProductDna.is_current.is_(True))
    ).all()

    alcanzadas: list[uuid.UUID] = []
    for product_id in productos:
        borrador = cargar_borrador(session, product_id)
        if borrador is None:
            continue
        ficha = ClassificationContext(
            description=borrador.summary or "",
            operation_date=datetime.now(UTC).date(),
            facts=tuple(ProductFact(**a.to_fact_fields()) for a in borrador.attributes),
        )
        if la_ficha_dice(termino, ficha):
            alcanzadas.append(product_id)

    ejemplos = [
        f"{sku} · {nombre or ''}".strip(" ·")
        for sku, nombre in session.execute(
            sa.select(Product.sku, Product.commercial_name)
            .where(Product.id.in_(alcanzadas[:EJEMPLOS_DE_ALCANCE]))
            .order_by(Product.sku)
        ).all()
    ]
    return AlcanceVocabulario(
        termino_ficha=termino,
        fichas=len(alcanzadas),
        de_un_total=len(productos),
        ejemplos=ejemplos,
    )


@router.post(
    "/vocabulario/{respuesta_id}/retirar",
    summary="Retira una respuesta de vocabulario que resultó equivocada, sin borrarla",
)
def retirar_vocabulario(
    respuesta_id: uuid.UUID, peticion: RetiroVocabulario, session: SessionDep
) -> VocabularioRetirado:
    """Una respuesta firmada que resultó equivocada deja de aplicarse y se queda.

    EL CASO (César, 6-oct)

    Contestó a «¿el cable cumple "Galvanizados"?» eligiendo el valor «acero»
    de la ficha. El sistema guardó «nada de acero es galvanizado», que él
    mismo llamó una generalización falsa: un cable puede ser de acero
    galvanizado, sin recubrimiento o con otro tratamiento. Pidió cerrarla
    como «respuesta incorrecta de alcance», no borrarla.

    NO SE CIERRA CON FECHA DE HOY, Y ESO ES LO QUE IMPORTA AQUÍ

    La vigencia de una respuesta de vocabulario sigue a la del texto de la
    tarifa que describe, no al día en que se contestó (ver
    `_desde_cuando_rige_la_tarifa`): ésta rige desde 2022. Cerrarla con
    `valid_to = hoy` la dejaría aplicándose a toda operación anterior a hoy
    —el corpus entero va de marzo a agosto de 2026—. Parecería cerrada y
    seguiría actuando.

    Una respuesta equivocada no caducó: nunca fue cierta. Así que `valid_to`
    se pone el día ANTERIOR a `valid_from`, y el filtro de vigencia
    —`valid_from <= fecha <= valid_to`— no la deja pasar para ninguna fecha.
    La fila se conserva entera, con el motivo añadido a su nota.

    LO QUE NO HACE

    No vuelve a clasificar: lo que cambia se ve en la siguiente
    reclasificación. Y como la pareja sigue en la tabla, el UNIQUE impide
    volver a contestar exactamente la misma con la misma fecha de inicio; si
    algún día hace falta, se discute antes de relajarlo.
    """
    fila = session.get(NomenclatureSynonym, respuesta_id, with_for_update=True)
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "respuesta de vocabulario no encontrada")
    if _esta_retirada(fila):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"esa respuesta ya está retirada (vigencia {fila.valid_from} → {fila.valid_to})",
        )

    hoy = datetime.now(UTC).date().isoformat()
    fila.valid_to = fila.valid_from - timedelta(days=1)
    fila.note = (
        f"{fila.note or ''} [RETIRADA el {hoy} por {peticion.reviewer}: {peticion.motivo}]"
    ).strip()
    session.commit()

    log.info(
        "review.vocabulario.retirada",
        respuesta_id=str(fila.id),
        reviewer=peticion.reviewer,
        commercial_term=fila.commercial_term,
        nomenclature_term=fila.nomenclature_term,
    )
    return VocabularioRetirado(
        id=fila.id,
        commercial_term=fila.commercial_term,
        nomenclature_term=fila.nomenclature_term,
        kind=fila.kind,
        valid_from=fila.valid_from,
        valid_to=fila.valid_to,
    )


@router.post(
    "/{decision_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Confirma, corrige o declara que falta información",
)
def revisar(
    decision_id: uuid.UUID, peticion: RevisionRequest, session: SessionDep
) -> RevisionResponse:
    """Registra el veredicto humano SIN borrar el de la máquina.

    Crea una decisión nueva marcada `HUMAN_VALIDATED` que apunta a la original
    por `reviews_decision_id`, y saca la original de la bandeja. Ese puntero es
    lo que la métrica usa para emparejarlas (§39).

    LA ORIGINAL SALE DE LA BANDEJA TAMBIÉN CUANDO FALTA INFORMACIÓN

    Puede parecer al contrario —el caso no está resuelto—, pero lo que le falta
    no es una opinión más: es un dato de la mercancía. Dejarlo en la bandeja
    garantizaría que el siguiente revisor gaste su rato en llegar a la misma
    conclusión, y el veredicto existe justamente para que eso no pase. Queda
    con `status = INSUFFICIENT_INFORMATION` y con la nota diciendo qué pedir.
    """
    # FOR UPDATE: dos veredictos simultáneos sobre el mismo caso tienen que
    # ordenarse, o los dos verían la decisión pendiente y los dos escribirían.
    original = session.get(ClassificationDecision, decision_id, with_for_update=True)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisión no encontrada")

    if original.data_origin == "HUMAN_VALIDATED":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "esta fila ya es una revisión humana: no se revisa una revisión",
        )

    if _ya_revisada(session, original.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "esta decisión ya tiene veredicto: un segundo la contaría dos veces en la métrica",
        )

    if peticion.veredicto == "CORRIGE" and not peticion.fraction_code:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "corregir exige la fracción correcta: sin ella la corrección no dice nada",
        )

    if peticion.veredicto == "FALTA_INFORMACION":
        if peticion.fraction_code:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "«falta información» y una fracción se contradicen: si hay fracción "
                "que proponer, el veredicto es CORRIGE",
            )
        if not (peticion.nota or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "«falta información» exige decir QUÉ dato falta: sin eso el veredicto "
                "cierra el caso sin desatascarlo, y nadie sabe qué pedir",
            )

    if peticion.veredicto == "CORRIGE":
        codigo = peticion.fraction_code
    elif peticion.veredicto == "FALTA_INFORMACION":
        # Sin fracción A PROPÓSITO: es exactamente lo que la persona afirma.
        # Heredar la del motor convertiría un «no se puede determinar» en una
        # confirmación de lo que el motor propuso.
        codigo = None
    else:
        codigo = original.fraction_code

    if peticion.nico_code and not codigo:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "un NICO sin fracción no identifica nada: el mismo «02» existe en miles "
            "de fracciones y sólo significa algo dentro de la suya",
        )

    # La fracción del veredicto se comprueba contra la tarifa. Un clasificador
    # es la autoridad sobre el CRITERIO, no sobre qué códigos existen, y un
    # dígito mal teclado no se convierte en fracción por venir de una persona.
    #
    # Pasó de verdad: se aceptó `73239399` para un sartén de acero inoxidable.
    # Bajo esa subpartida sólo existe `73239305`, y la decisión quedó guardada,
    # contada en el tablero y pintada en verde en la pantalla de Classification
    # —como «la única verdad del sistema que no generamos nosotros»— con una
    # fracción que no está en la TIGIE.
    #
    # Se comprueba con la fecha DE LA OPERACIÓN, no con hoy: una fracción
    # derogada existió, y un veredicto sobre una operación de 2022 puede citarla
    # legítimamente (regla 5).
    #
    # Y sólo se acusa si HAY tarifa cargada: un catálogo vacío no demuestra que
    # la fracción no exista, sólo que no lo sabemos. Sin esta condición el
    # guardarraíl rechazaba todos los veredictos en cualquier entorno sin
    # tarifa —incluida una instalación nueva del cliente.
    if codigo:
        catalogo = TariffCatalogRepository(session)
        hay_tarifa = catalogo.hay_fracciones(on_date=original.operation_date)
        if hay_tarifa and not catalogo.fraccion_existe(
            on_date=original.operation_date, code=codigo
        ):
            hermanas = catalogo.hermanas_de(on_date=original.operation_date, code=codigo)
            # Se enseña lo que hay, no se propone una. Elegir por la persona
            # sería justo lo que esta comprobación existe para impedir.
            existen = ", ".join(hermanas) if hermanas else "ninguna"
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"la fracción {codigo} no existe en la TIGIE vigente al "
                f"{original.operation_date.isoformat()}. En la subpartida "
                f"{codigo[:6]} existen: {existen}",
            )

        # EL NICO SE COMPRUEBA APARTE Y DESPUÉS, PORQUE ES OTRO NIVEL
        #
        # Aparte, porque sólo tiene sentido DENTRO de la fracción ya validada:
        # preguntar si el «02» existe sin decir en qué fracción no tiene
        # respuesta. Y después, porque con una fracción inexistente el catálogo
        # no puede decir nada de sus NICO y el error que importa es el primero.
        #
        # Vale la misma disciplina de tres respuestas de `nicos()`: `None` (la
        # fracción no está vigente ese día) y `()` (existe y no tiene NICO
        # cargados) son huecos NUESTROS y no autorizan a rechazar el veredicto
        # de nadie. Sólo con códigos cargados se puede afirmar que el dígito
        # está mal — el mismo criterio que `hay_tarifa` para la fracción.
        if peticion.nico_code:
            vigentes = catalogo.nicos(on_date=original.operation_date, fraction_code=codigo)
            if vigentes and peticion.nico_code not in vigentes:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"el NICO {peticion.nico_code} no existe en la fracción {codigo} "
                    f"vigente al {original.operation_date.isoformat()}. En esa "
                    f"fracción existen: {', '.join(vigentes)}",
                )

    revision = ClassificationDecision(
        product_id=original.product_id,
        product_dna_id=original.product_dna_id,
        # Qué revisa. Es lo que empareja el veredicto con SU decisión en la
        # métrica, en vez de con la más reciente del mismo DNA.
        reviews_decision_id=original.id,
        trade_flow=original.trade_flow,
        operation_date=original.operation_date,
        # `INSUFFICIENT_INFORMATION` es literalmente lo que la persona dijo, y
        # es distinto de `HUMAN_REVIEW_REQUIRED`: el segundo pide otra opinión,
        # el primero pide un DATO. Confundirlos devolvería el caso a una
        # bandeja donde el siguiente revisor llegaría a la misma conclusión.
        status=(
            "INSUFFICIENT_INFORMATION"
            if peticion.veredicto == "FALTA_INFORMACION"
            else ("RESOLVED" if codigo else "HUMAN_REVIEW_REQUIRED")
        ),
        chapter=codigo[:2] if codigo else None,
        heading=codigo[:4] if codigo else None,
        subheading=codigo[:6] if codigo else None,
        fraction_code=codigo,
        # El segundo nivel de la decisión. `nico_id` se queda en NULL: ligarlo
        # al catálogo exigiría resolver la fila de `regulatory.nicos` y el
        # código ya se validó contra ella — igual que el motor, que escribe el
        # código y no el puntero.
        nico_code=peticion.nico_code,
        reasoning=_razonamiento(peticion, original),
        rgi_path=list(original.rgi_path or []),
        # La traza es del motor. Copiarla aquí haría parecer que la persona
        # siguió esas reglas, y no las siguió: revisó su conclusión.
        rgi_trace=None,
        engine_version=original.engine_version,
        # HUMAN_VALIDATED es lo que distingue esta fila de la del motor y lo
        # que permite emparejarlas al evaluar (§39).
        data_origin="HUMAN_VALIDATED",
        # Ya la revisó una persona: no vuelve a la bandeja.
        requires_human_review=False,
        confidence=None,
    )
    session.add(revision)

    # La original se conserva intacta salvo por salir de la bandeja: es la
    # respuesta de la máquina y es la mitad de la métrica.
    original.requires_human_review = False
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if _es_veredicto_duplicado(exc):
            # Dos POST llegaron a escribir a la vez y el UNIQUE decidió.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "esta decisión ya tiene veredicto: un segundo la contaría dos veces en la métrica",
            ) from exc
        raise

    return RevisionResponse(
        original_id=original.id,
        revision_id=revision.id,
        veredicto=peticion.veredicto,
        fraction_code=codigo,
        nico_code=peticion.nico_code,
    )


def _razonamiento(peticion: RevisionRequest, original: ClassificationDecision) -> str:
    """Deja por escrito quién revisó, qué dijo y sobre qué.

    Una corrección sin motivo no sirve para entrenar: se sabe que el sistema
    se equivocó, no en qué.
    """
    partes = [f"Revisión humana de {peticion.reviewer}: {peticion.veredicto.lower()}."]
    if peticion.veredicto == "CORRIGE":
        partes.append(
            f"El motor propuso {original.fraction_code or 'sin fracción'}; "
            f"se corrige a {peticion.fraction_code}."
        )
    elif peticion.veredicto == "FALTA_INFORMACION":
        partes.append(
            f"El motor propuso {original.fraction_code or 'sin fracción'}; "
            "quien revisa dice que la ficha no alcanza para determinarla y "
            "que el dato hay que pedirlo, no suponerlo."
        )
    if peticion.nico_code:
        # En su propia frase, no pegado a la fracción: son dos niveles y
        # escribirlos juntos («7312100502») es el error que esta nota existe
        # para no cometer.
        partes.append(f"NICO {peticion.nico_code}.")
    if peticion.nota:
        partes.append(peticion.nota)
    return " ".join(partes)
