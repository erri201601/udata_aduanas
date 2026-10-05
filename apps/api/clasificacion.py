"""La tubería de clasificación, sin persistir: DNA → normas → motor.

Existe como función aparte por una razón: el harness de `hs_accuracy` tiene que
medir EXACTAMENTE el camino que usa `POST /products/{id}/classify`. Si el
harness copiara la tubería, el día que alguien cambie la consulta jurídica o el
embedder en el router, el número seguiría midiendo la versión vieja sin que
nadie lo notara.

No escribe nada. Quien quiera guardar el resultado —el router— llama después a
`save_classification`. El harness no lo hace nunca.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from core.classification import classify_product, fundamenta_clasificacion
from database.models import LegalDocument, NomenclatureSynonym
from database.repositories.chunks import PostgresChunkStore
from database.repositories.notes import LegalNotesRepository
from database.repositories.tariff import TariffCatalogRepository
from rag import a_legal_refs, embedder_opcional, recuperar

from apps.api.dna import MAX_TERMINOS, MIN_LONGITUD_TERMINO, palabras_de

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import date

    from core.classification import ClassificationOutcome
    from core.evidence.types import LegalRef
    from core.product_dna.types import ProductDnaDraft
    from rag import EmbedderDegradable
    from rag.retrieval import Recuperacion
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Clasificado:
    """El resultado del motor y lo que hace falta para declararlo."""

    outcome: ClassificationOutcome
    legal_refs: tuple[LegalRef, ...]
    hay_notas: bool
    embedder: EmbedderDegradable | None
    consulta_juridica: str

    @property
    def uso_vectores(self) -> bool:
        return self.embedder is not None and self.embedder.uso_vectores


def _busqueda(session: Session, borrador: ProductDnaDraft, on_date: date) -> list[str]:
    """Los términos con los que se busca en la nomenclatura.

    LOS PUENTES VAN AL FINAL, Y ESO COSTÓ UNA RESPUESTA EQUIVOCADA

    Probé a ponerlos primero, razonando que un término que SABEMOS que aparece
    en la tarifa discrimina más que una palabra comercial. La tubería del
    corpus pasó a resolver `73045112` —tubos SIN SOLDADURA— para una mercancía
    soldada.

    La causa: `7304` y `7305` dicen los dos «de los tipos utilizados en
    oleoductos o gasoductos». Poner el puente en cabeza empujó «SOLDADA» fuera
    del tope de seis, y era justo la palabra que separaba una de otra.

    Los puentes se BUSCAN sobre todas las palabras de la ficha —si no, uno que
    cae en la posición 10 no se dispara nunca— pero se AÑADEN detrás: pueden
    hacer que el motor encuentre más candidatas, nunca que pierda la palabra
    que ya discriminaba.
    """
    palabras = palabras_de(borrador)
    puentes = _con_sinonimos(session, palabras, on_date=on_date)
    nuevos = [t for t in puentes if t not in palabras]
    # EL PUENTE NO LLEGA A LA CONSULTA, Y HOY ESO ES LO CORRECTO
    #
    # `palabras_de` devuelve la ficha ENTERA sin truncar —once palabras en la
    # tubería del corpus, ocho en el estropajo, diez en el cable galvanizado—
    # así que este corte cae siempre antes del primer puente. Medido ficha por
    # ficha el 5-oct: TODAS las del corpus tienen seis palabras o más, así que
    # ningún puente puede aplicarse a nada. La mesa de vocabulario —tabla,
    # endpoint, tests y documentación— no puede cambiar ni una clasificación.
    #
    # Lo probé. Dejé pasar los puentes por encima del tope y medí:
    #
    #                        contestó  acertó  falló  precisión  cobertura
    #     sin puentes             54      54      0    100.00 %    32.14 %
    #     con puentes             60      43     17     71.67 %    35.71 %
    #
    # Los 17 fallos son dos familias, y las dos dicen lo mismo: el puente no
    # sólo ayuda a ENCONTRAR candidatas, también le da un punto de cobertura a
    # la posición de cuyo texto salió, y con eso le hace GANAR el recorte por
    # cobertura máxima.
    #
    #     14 vajillas  «VAJILLA DE CERAMICA VIDRIADA, NO PORCELANA»
    #                  el puente «vajilla» → «mesa» sale del texto de la 6911
    #                  («de porcelana»), que pasó a cubrir un término más que
    #                  la 6912 y a expulsarla de las candidatas. Las 14 estaban
    #                  BIEN antes.
    #      3 utensilios de acero inoxidable
    #                  se abstenían, y con el puente pasaron a resolver 732310
    #                  —lana, esponjas, estropajos—, que no es lo que son.
    #
    # Y el código de la RGI 3 ya tiene escrita la regla que decide esto: «una
    # mejora que convierte una negativa honesta en una fracción equivocada no
    # es una mejora». Aquí además convierte catorce aciertos en errores.
    #
    # Así que el puente se queda fuera hasta que la cobertura sepa distinguir
    # un término de la ficha de un puente: buscar con él, sí; ganar con él, no.
    # Eso toca el puerto `TariffCatalog` y su SQL, y pide su propia medición.
    # El emparejamiento (`_lo_dice_la_ficha`) ya está arreglado y esperando.
    return (palabras + nuevos)[:MAX_TERMINOS]


def _exclusiones(session: Session, *, on_date: date) -> list[tuple[str, str]]:
    """Las parejas que un clasificador declaró distintas, vigentes ese día.

    SÓLO `HUMAN_VALIDATED`. Una exclusión escrita por nosotros es conjetura, y
    una conjetura no puede hacer imposible una posición de la tarifa: eso es
    descartar fundamento sin fundamento. Las nuestras sirven para BUSCAR
    (`EQUIVALE`), nunca para descartar.
    """
    vigentes = sa.and_(
        NomenclatureSynonym.valid_from <= on_date,
        sa.or_(
            NomenclatureSynonym.valid_to.is_(None),
            NomenclatureSynonym.valid_to >= on_date,
        ),
    )
    filas = session.execute(
        sa.select(NomenclatureSynonym.commercial_term, NomenclatureSynonym.nomenclature_term).where(
            vigentes,
            NomenclatureSynonym.kind == "EXCLUYE",
            NomenclatureSynonym.data_origin == "HUMAN_VALIDATED",
        )
    ).all()
    return [(f.commercial_term, f.nomenclature_term) for f in filas]


def _lo_dice_la_ficha(termino_comercial: str, palabras_ficha: set[str]) -> bool:
    """¿Están en la ficha todas las palabras distintivas del término?

    UN TÉRMINO DE DOS PALABRAS NO PODÍA CASAR NUNCA

    Esto comparaba `commercial_term` con igualdad exacta contra cada palabra de
    la ficha (`lower(commercial_term) IN base`), y `palabras_de` devuelve
    PALABRAS sueltas. Así que `«acero inoxidable»`, `«sin recubrimiento»` o
    `«domestico/cocina»` no podían casar con nada: no son una palabra.

    No se había notado porque las nueve filas que había eran de una sola
    palabra —`conduccion`, `limpieza`, `galvanizado`—. La primera vez que un
    clasificador contestó mirando dos palabras de la ficha, su respuesta quedó
    firmada, guardada y sin efecto.

    Ahora se empareja como lo hace la exclusión en el motor: por subconjunto de
    palabras distintivas. Con una sola palabra el resultado es idéntico al de
    antes, así que las nueve filas viejas se comportan igual.

    Un término sin ninguna palabra distintiva —`«6x19»`, todo dígitos— devuelve
    `False` y no puede disparar un puente. Es deliberado y es el límite de esta
    vía: un número no ensancha una búsqueda de texto. Para descartar sí sirve,
    porque la exclusión compara contra el texto entero de la ficha.
    """
    distintivas = {
        p.casefold()
        for p in re.findall(r"[^\W\d_]+", termino_comercial)
        if len(p) >= MIN_LONGITUD_TERMINO
    }
    return bool(distintivas) and distintivas <= palabras_ficha


def _con_sinonimos(session: Session, terminos_base: list[str], *, on_date: date) -> list[str]:
    """Añade los términos de nomenclatura equivalentes a los de la ficha.

    Se AÑADEN, nunca sustituyen: si el puente estuviera mal, el término
    original sigue ahí y la búsqueda no pierde nada. Un puente sólo puede
    hacer que el motor encuentre MÁS candidatas, nunca menos, y de ahí en
    adelante las reglas deciden igual que siempre.

    SÓLO `EQUIVALE`

    La consulta no filtraba por `kind` y usaba también el término de las filas
    `EXCLUYE`. Una exclusión dice que la ficha NO es eso; meterlo como término
    de búsqueda empujaría al motor justo hacia la posición que el clasificador
    descartó. Con `«ceramica vidriada» → «talavera»` cargada, una vajilla que
    no es Talavera habría buscado «talavera».

    No llegó a pasar porque ninguna de las dos filas `EXCLUYE` de dos palabras
    podía casar con la igualdad exacta de antes. Al arreglar el emparejamiento,
    sí habría pasado.
    """
    vigentes = sa.and_(
        NomenclatureSynonym.valid_from <= on_date,
        sa.or_(
            NomenclatureSynonym.valid_to.is_(None),
            NomenclatureSynonym.valid_to >= on_date,
        ),
    )
    filas = session.execute(
        sa.select(NomenclatureSynonym.commercial_term, NomenclatureSynonym.nomenclature_term).where(
            vigentes, NomenclatureSynonym.kind == "EQUIVALE"
        )
    ).all()

    base = {t.casefold() for t in terminos_base}
    palabras_ficha = {t.casefold() for t in terminos_base}
    salida = list(terminos_base)
    for comercial, nomenclatura in filas:
        if not _lo_dice_la_ficha(comercial, palabras_ficha):
            continue
        if nomenclatura.casefold() in base:
            continue
        base.add(nomenclatura.casefold())
        salida.append(nomenclatura)
    return salida


def clasificar_borrador(
    session: Session,
    borrador: ProductDnaDraft,
    *,
    operation_date: date,
    trade_flow: str,
    search_terms: Sequence[str] | None = None,
) -> Clasificado:
    """Clasifica un Product DNA con el corpus vigente en `operation_date` (§14).

    Si el proveedor de vectores no está o falla, `embedder_opcional` lo absorbe
    y se sigue por término y vigencia. Clasificar es lo que no puede dejar de
    ocurrir; buscar por significado es lo que lo hace mejor.
    """
    # Import diferido: el router importa este módulo, y la consulta jurídica
    # vive en el router desde el PR #54.
    from apps.api.routers.products import _consulta_juridica

    notas = LegalNotesRepository(session)
    busqueda = list(search_terms) if search_terms else _busqueda(session, borrador, operation_date)
    # El puente de vocabulario (§18): una ficha dice «para conducción de
    # fluidos» y la tarifa dice «de los tipos utilizados en oleoductos o
    # gasoductos». Sin esto el motor no puede casar dos textos que hablan de lo
    # mismo y se niega sin necesidad.
    #
    # Los puentes NO fundamentan: la decisión se sigue sosteniendo en el texto
    # de la tarifa. Y van marcados —hoy todos `SYNTHETIC`— porque los
    # escribimos nosotros y ningún clasificador los ha validado todavía.

    consulta = _consulta_juridica(busqueda)

    embedder = embedder_opcional()
    recuperacion = recuperar(
        consulta,
        on_date=operation_date,
        store=PostgresChunkStore(session),
        embedder=embedder,
    )
    legal_refs = a_legal_refs(_solo_lo_que_funda_una_clasificacion(session, recuperacion))

    outcome = classify_product(
        borrador,
        operation_date=operation_date,
        catalog=TariffCatalogRepository(session),
        notes=notas,
        search_terms=busqueda,
        legal_refs=legal_refs,
        # Lo que un clasificador ya contestó: parejas que NO son lo mismo.
        # Sólo las firmadas — una conjetura nuestra no puede descartar una
        # posición de la tarifa.
        exclusiones=_exclusiones(session, on_date=operation_date),
        trade_flow=trade_flow,
    )
    return Clasificado(
        outcome=outcome,
        legal_refs=legal_refs,
        hay_notas=notas.hay_corpus(on_date=operation_date),
        embedder=embedder,
        consulta_juridica=consulta,
    )


def _solo_lo_que_funda_una_clasificacion(
    session: Session, recuperacion: Recuperacion
) -> Recuperacion:
    """Descarta lo recuperado que no puede fundamentar una CLASIFICACIÓN.

    `a_legal_refs` ya filtra por procedencia —lo sintético no fundamenta— pero
    eso es una dimensión distinta de ésta. El artículo 78 de la Ley Aduanera es
    oficial, vigente y verificable, y aun así no sustenta dónde clasifica una
    mercancía: habla de cómo determinar el valor en aduana.

    El filtro va aquí y no dentro del RAG a propósito: recuperar sigue
    devolviendo todo lo que rige ese día, porque el Copilot y el Sentinel sí
    quieren la Ley Aduanera. Lo que cambia es qué se le entrega al motor como
    fundamento de esta decisión concreta.

    Un documento cuyo tipo no se puede resolver NO pasa: no se presume
    fundamento lo que no se pudo comprobar.
    """
    if not recuperacion.chunks:
        return recuperacion

    ids = {c.document_id for c in recuperacion.chunks if c.document_id}
    tipos: dict[uuid.UUID, str] = {
        fila.id: fila.kind
        for fila in session.execute(
            sa.select(LegalDocument.id, LegalDocument.kind).where(LegalDocument.id.in_(ids))
        )
    }
    fundamentables = tuple(
        c
        for c in recuperacion.chunks
        # Sin `document_id` no hay forma de saber de qué instrumento sale, y lo
        # que no se puede comprobar no se presume fundamento.
        if c.document_id is not None and fundamenta_clasificacion(tipos.get(c.document_id))
    )
    return recuperacion.model_copy(update={"chunks": fundamentables})
