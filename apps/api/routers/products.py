"""Lectura de productos y su Product DNA (§16).

Escribe por tres puertas —texto pegado, PDF e imagen— y las tres pasan por el
Product DNA Engine (`core.product_dna.engine.extract`) y por `guardar_dna`: no
hay forma de escribir atributos sin estado, sin evidencia o sin el crudo
guardado antes.

Los esquemas salen de `schemas/`, tal cual los definió Persona 2. No se
declaran formas nuevas: si un campo faltara, se acuerda con él en vez de
inventar una variante que después no cuadre con la tabla.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, cast

import sqlalchemy as sa
from core.evidence.builder import model_output
from core.evidence.types import DocumentRef
from core.llm.errors import ProviderNotConfiguredError, ProviderResponseError
from core.llm.registry import get_default_provider
from core.product_dna.engine import extract as extraer_dna
from core.product_dna.llm_extractor import LlmExtractor
from core.product_dna.pdf import MAXIMO_CARACTERES as MAXIMO_CARACTERES_PDF
from core.product_dna.pdf import (
    PdfDemasiadoLargoError,
    PdfIlegibleError,
    SinTextoExtraibleError,
    texto_con_paginas,
)
from core.product_dna.types import SourceDocument
from core.product_dna.vision import MEDIA_TYPES, VisionExtractor
from database.models import Product, ProductAttribute, ProductDna
from database.repositories import save_classification
from database.repositories.product_dna import guardar_dna
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from ingestion.snice.raw import RawCapture, content_hash, local_target, store_raw_bytes
from pydantic import BaseModel, Field
from rag import (
    MODO_SEMANTICO,
    MODO_TERMINO,
    EmbedderDegradable,
)
from schemas.intelligence import ProductAttributeRead, ProductDnaRead
from schemas.operational import ProductRead

from apps.api.clasificacion import clasificar_borrador
from apps.api.db import SessionDep
from apps.api.dna import cargar_borrador, version_vigente
from apps.api.logging import get_logger

if TYPE_CHECKING:
    from core.evidence.types import Evidence
    from core.llm.base import ModelProvider
    from core.llm.types import CallMetadata

log = get_logger("apps.api.products")

router = APIRouter(prefix="/products", tags=["products"])

#: Tope de página. El catálogo de un cliente puede tener miles de productos y
#: una respuesta sin límite es una descarga completa disfrazada de consulta.
LIMITE_MAXIMO = 200


class ProductDnaDetail(ProductDnaRead):
    """Un Product DNA con sus atributos.

    Van juntos porque nunca se necesitan por separado: un DNA sin sus
    atributos no dice nada, y la pantalla tendría que encadenar dos peticiones
    para pintar una sola vista.
    """

    attributes: list[ProductAttributeRead] = Field(default_factory=list)


@router.get("", summary="Lista los productos del catálogo")
def listar_productos(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProductRead]:
    """Productos ordenados por SKU, que es lo que el usuario reconoce."""
    filas = session.scalars(
        sa.select(Product).order_by(Product.sku).limit(limit).offset(offset)
    ).all()
    return [ProductRead.model_validate(f, from_attributes=True) for f in filas]


@router.get("/{product_id}", summary="Un producto del catálogo")
def obtener_producto(product_id: uuid.UUID, session: SessionDep) -> ProductRead:
    fila = session.get(Product, product_id)
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "producto no encontrado")
    return ProductRead.model_validate(fila, from_attributes=True)


@router.get(
    "/{product_id}/dna",
    summary="Product DNA vigente del producto, con sus atributos",
)
def obtener_dna(product_id: uuid.UUID, session: SessionDep) -> ProductDnaDetail:
    """El DNA marcado como vigente.

    Se filtra por `is_current` y no por la versión más alta: un DNA se puede
    reemplazar por una revisión humana que no sea la última generada, y la
    columna es la que decide cuál rige.
    """
    if session.get(Product, product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "producto no encontrado")

    dna = session.scalars(
        sa.select(ProductDna)
        .where(ProductDna.product_id == product_id, ProductDna.is_current.is_(True))
        .order_by(ProductDna.version.desc())
    ).first()
    if dna is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "el producto no tiene Product DNA vigente",
        )

    atributos = session.scalars(
        sa.select(ProductAttribute)
        .where(ProductAttribute.product_dna_id == dna.id)
        .order_by(ProductAttribute.name)
    ).all()

    detalle = ProductDnaDetail.model_validate(dna, from_attributes=True)
    return detalle.model_copy(
        update={
            "attributes": [
                ProductAttributeRead.model_validate(a, from_attributes=True) for a in atributos
            ]
        }
    )


class ClassifyRequest(BaseModel):
    """Qué hace falta para clasificar, más allá del producto."""

    operation_date: date
    """Obligatoria (§14). Sin ella no se puede saber qué tarifa regía, y
    clasificar con la de hoy una operación de 2024 da un resultado que parece
    correcto y no lo es."""

    trade_flow: str = "IMPORT"
    search_terms: list[str] = Field(default_factory=list)
    """Términos con los que buscar en la nomenclatura. Vacío usa el resumen
    del Product DNA."""


class ClassifyResponse(BaseModel):
    """El resultado, con lo que hay que saber para leerlo."""

    decision_id: uuid.UUID
    status: str
    fraction_code: str | None = None
    nico_code: str | None = None
    """Sólo cuando la LIGIE da un único NICO para la fracción (§19)."""
    nico_motivo: str | None = None
    """Por qué hay o no hay NICO."""
    confidence: Decimal | None = None
    requires_human_review: bool
    trace_steps: int
    """Cuántas reglas se evaluaron. Es lo que la pantalla va a mostrar."""

    legal_refs_used: int = 0
    """Cuántas normas sostienen esta clasificación.

    Cero significa que el resultado no es defendible: el contrato de evidencia
    lo bloquea, y con razón — una fracción sin norma detrás no se declara.
    """

    classified_without_legal_notes: bool
    """¿Se clasificó sin notas de sección ni capítulo?

    La RGI 1 dice que la clasificación se determina por los textos de las
    partidas Y por las notas. Mientras `regulatory.legal_rules` esté vacía no
    se pueden descartar partidas por exclusión, y el resultado es menos
    fundamentado. Se declara en vez de dejar que parezca que se consultaron y
    no excluían nada.
    """

    blocked_by: str | None = None

    modo_busqueda: str = MODO_TERMINO
    """Cómo se recuperaron las normas que sostienen esta clasificación.

    No es un detalle de implementación: dos clasificaciones del mismo producto
    con distinto modo se apoyan en normas que pudieron ser distintas, y quien
    audite la decisión tiene que poder saberlo. Se declara aquí porque la
    decisión persiste y el modo no.
    """

    degradado_por: str | None = None
    """Por qué se buscó por término en vez de por significado.

    `None` cuando no hubo degradación. Una clasificación NUNCA falla porque el
    proveedor de vectores esté caído (Persona 1, 2026-09-09): se busca peor,
    se dice, y se sigue. Callarlo sería peor que degradar.
    """


#: Lo que hay que preguntarle al corpus jurídico para fundamentar una
#: clasificación. Son conceptos de la Ley Aduanera, no del producto.
CONCEPTOS_DE_CLASIFICACION = (
    "clasificación arancelaria de las mercancías",
    "valor en aduana base gravable de la importación",
    "fracción arancelaria declarada en el pedimento",
)


def _porque_no_vectores(embedder: EmbedderDegradable | None) -> str:
    """Por qué esta clasificación no usó vectores. Siempre hay razón que dar."""
    if embedder is None:
        return "no hay proveedor de embeddings configurado"
    if embedder.motivo_degradacion:
        return f"el proveedor falló y se siguió por término: {embedder.motivo_degradacion}"
    return "no se intentó vectorizar la consulta"


def _consulta_juridica(terminos_producto: list[str]) -> str:
    """Con qué buscar en la Ley Aduanera para sostener una clasificación.

    NO se busca con los atributos del producto. La ley no habla de laptops ni
    de kilogramos: habla de clasificación, valor en aduana y obligaciones del
    importador. Buscar «Laptop portátil pulgadas» en la Ley Aduanera devuelve
    cero, y lo comprobé contra el corpus real antes de escribir esto.

    Los términos del producto se conservan al final porque alguno puede
    aparecer de verdad en la norma —«vehículo», «combustible», «alcohol»
    tienen artículos propios— y en ese caso son lo más pertinente que se puede
    recuperar. Van después de los conceptos para no desplazarlos.
    """
    return " ".join([*CONCEPTOS_DE_CLASIFICACION, *terminos_producto[:3]])


#: imagen de más de esto casi nunca es una foto de producto, y el proveedor de
#: visión la rechazaría después de habernos costado el viaje.
MAXIMO_IMAGEN_BYTES = 8 * 1024 * 1024

#: Una ficha técnica en PDF rara vez pasa de unos pocos MB. Más es un manual o
#: un catálogo escaneado, y lo segundo no tiene texto que leer.
MAXIMO_PDF_BYTES = 15 * 1024 * 1024

#: Cómo se nombra cada entrada en la evidencia, para quien la lea después.
_ENTRADA: dict[str, str] = {
    "text": "texto pegado",
    "pdf": "PDF",
    "image": "imagen",
}


class DnaExtraido(BaseModel):
    """Lo que se extrajo, de dónde salió y si sustituyó a la ficha vigente."""

    product_dna_id: uuid.UUID
    version: int
    atributos: int
    """Los atributos que el documento SÍ aportó. Los MISSING no cuentan: el
    motor devuelve siempre los 18 del catálogo."""
    summary: str | None = None
    missing_information: list[str] = Field(default_factory=list)

    vigente: bool
    """¿Esta versión es ahora la ficha del producto?

    `False` cuando la extracción no encontró nada: se guarda, porque el intento
    ocurrió y consta, pero no sustituye a la ficha que había (`guardar_dna`).
    Sin decirlo, quien sube un escaneo vería «versión 7» y creería que el
    producto se quedó sin datos."""

    evidence_id: uuid.UUID | None = None
    """La evidencia MODEL_OUTPUT de la extracción, a la que apuntan la ficha y
    cada atributo. `None` sólo si el extractor no dejó metadata de la llamada."""

    minio_key: str
    """Dónde quedó el crudo. Sin esto no se puede volver al archivo."""
    content_hash: str
    """El hash del archivo TAL COMO SE RECIBIÓ. Es lo que prueba, meses
    después, que el atributo salió de ese archivo y no de otro."""


class TextoDeFicha(BaseModel):
    """Una ficha técnica pegada como texto."""

    texto: str = Field(min_length=20, max_length=MAXIMO_CARACTERES_PDF)
    """El texto tal cual. Menos de 20 caracteres no describe una mercancía."""
    nombre: str | None = Field(default=None, max_length=200)
    """De dónde se copió, si se sabe: «datasheet del fabricante, rev. B»."""


def _producto(session: SessionDep, product_id: uuid.UUID) -> Product:
    producto = session.get(Product, product_id)
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "producto no encontrado")
    return producto


def _guardar_crudo(product_id: uuid.UUID, datos: bytes, nombre: str) -> RawCapture:
    """El archivo, entero y con su hash, ANTES de leerlo (§12, regla 7).

    Si el orden fuera el otro, un fallo del proveedor dejaría atributos sin
    documento del que dijeran venir. Lo único irreversible es el crudo.
    """
    return store_raw_bytes(
        datos,
        source_url=f"upload://producto/{product_id}/{nombre}",
        minio_key=f"product-dna/{product_id}/{content_hash(datos)}",
        target=local_target(),
    )


def _evidencia(
    metadata: CallMetadata | None, crudo: RawCapture, documento: SourceDocument, nombre: str
) -> Evidence | None:
    """La evidencia de la extracción: qué modelo, con qué prompt, sobre qué archivo.

    `MODEL_OUTPUT`, nunca fundamento jurídico: describe la mercancía, no la
    clasifica. El hash y la clave de MinIO van en `document_refs` (Persona 1,
    13-oct), que es lo que permite volver al archivo exacto.
    """
    if metadata is None:
        return None
    evidencia = model_output(
        summary=f"Product DNA extraído de {_ENTRADA.get(documento.kind, documento.kind)}: {nombre}",
        model_provider=metadata.model_provider,
        model_name=metadata.model_name,
        prompt_id=metadata.prompt_id or "",
        prompt_version=metadata.prompt_version or "",
    )
    return evidencia.model_copy(
        update={
            "document_ref": DocumentRef(
                document=f"{_ENTRADA.get(documento.kind, documento.kind)} subido: {nombre}",
                url=crudo.minio_key,
                content_hash=crudo.content_hash,
            ),
            "content_hash": crudo.content_hash,
        }
    )


def _extraer_y_guardar(
    session: SessionDep,
    producto: Product,
    *,
    crudo: RawCapture,
    documento: SourceDocument,
    nombre: str,
    nuevo_extractor: Callable[[], Any],
) -> DnaExtraido:
    """Lo común a las tres entradas, una vez el crudo está guardado.

    PASA POR EL MOTOR, NO SÓLO POR EL EXTRACTOR

    Hasta el 13-oct la imagen llamaba a `extractor.extract()` directamente y se
    saltaba `core.product_dna.engine.extract`: las reglas de saneamiento —un
    OBSERVED o EXTRACTED sin localizador baja a INFERRED, una inferencia sin
    confianza es MISSING— no se aplicaban a lo que entraba por foto. Ahora las
    tres entradas pasan por el motor, que es donde viven esas reglas.

    EL ORIGEN LO HEREDA DEL PRODUCTO

    El DNA de un producto sintético es `SYNTHETIC` aunque el archivo y el
    modelo sean reales. Un sexto valor para «lo que subió un usuario» rompería
    los cinco cerrados del §9.
    """
    try:
        extractor = nuevo_extractor()
        borrador = extraer_dna(documento, extractor=extractor)
    except ProviderNotConfiguredError as exc:
        # El crudo YA está guardado y eso no se deshace: el archivo existe y su
        # hash consta, aunque no hayamos podido leerlo. Se dice cuál falta.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"no hay proveedor de modelo configurado: {exc}",
        ) from exc
    except ProviderResponseError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"el proveedor de modelo no devolvió algo utilizable: {exc}",
        ) from exc

    metadata = getattr(extractor, "last_metadata", None)
    dna = guardar_dna(
        session,
        borrador,
        product_id=producto.id,
        data_origin=producto.data_origin,
        evidencia=_evidencia(metadata, crudo, documento, nombre),
        telemetria=metadata,
    )
    session.commit()

    log.info(
        "product_dna.guardado",
        product_id=str(producto.id),
        entrada=documento.kind,
        version=dna.version,
        vigente=dna.is_current,
        atributos=len(borrador.known()),
        content_hash=crudo.content_hash,
    )
    return DnaExtraido(
        product_dna_id=dna.id,
        version=dna.version,
        atributos=len(borrador.known()),
        summary=borrador.summary,
        missing_information=list(borrador.missing_information),
        vigente=bool(dna.is_current),
        evidence_id=dna.evidence_id,
        minio_key=crudo.minio_key,
        content_hash=crudo.content_hash,
    )


@router.post(
    "/{product_id}/dna/from-text",
    status_code=status.HTTP_201_CREATED,
    summary="Extrae el Product DNA de una ficha técnica pegada como texto (§16)",
)
def dna_desde_texto(
    product_id: uuid.UUID, peticion: TextoDeFicha, session: SessionDep
) -> DnaExtraido:
    """El texto también se guarda crudo: es el documento del que dirán venir los
    atributos, y sin su hash nadie podría comprobar después qué se pegó."""
    producto = _producto(session, product_id)
    nombre = peticion.nombre or "texto.txt"
    crudo = _guardar_crudo(product_id, peticion.texto.encode("utf-8"), nombre)
    return _extraer_y_guardar(
        session,
        producto,
        crudo=crudo,
        documento=SourceDocument(text=peticion.texto, kind="text", reference=crudo.minio_key),
        nombre=nombre,
        nuevo_extractor=lambda: LlmExtractor(cast("ModelProvider", get_default_provider())),
    )


@router.post(
    "/{product_id}/dna/from-pdf",
    status_code=status.HTTP_201_CREATED,
    summary="Extrae el Product DNA de una ficha técnica en PDF (§16, §48)",
)
def dna_desde_pdf(
    product_id: uuid.UUID,
    session: SessionDep,
    pdf: Annotated[UploadFile, File(description="Ficha técnica o datasheet en PDF")],
) -> DnaExtraido:
    """El primer eslabón del §48 dice «ficha técnica + imagen». Ésta es la ficha.

    Se saca la capa de texto con `[p.N]` delante de cada página y se pasa por el
    extractor de texto. Sin capa de texto —un escaneo— la respuesta es 422 «sin
    texto extraíble»: no hay OCR, y no se guarda ninguna ficha. El crudo sí
    queda guardado, porque se subió y consta.
    """
    producto = _producto(session, product_id)

    datos = pdf.file.read()
    if not datos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "el PDF llegó vacío")
    if len(datos) > MAXIMO_PDF_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"el PDF pesa {len(datos)} bytes y el máximo son {MAXIMO_PDF_BYTES}",
        )
    # Por la firma y no por el `content_type`: el navegador lo deduce de la
    # extensión, y un .pdf renombrado no es un PDF.
    if not datos.startswith(b"%PDF-"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "el archivo no es un PDF (no empieza por %PDF-)"
        )

    nombre = pdf.filename or "ficha.pdf"
    crudo = _guardar_crudo(product_id, datos, nombre)

    try:
        texto = texto_con_paginas(datos)
    except SinTextoExtraibleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except PdfIlegibleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except PdfDemasiadoLargoError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc

    return _extraer_y_guardar(
        session,
        producto,
        crudo=crudo,
        documento=SourceDocument(text=texto, kind="pdf", reference=crudo.minio_key),
        nombre=nombre,
        nuevo_extractor=lambda: LlmExtractor(cast("ModelProvider", get_default_provider())),
    )


@router.post(
    "/{product_id}/dna/from-image",
    status_code=status.HTTP_201_CREATED,
    summary="Extrae el Product DNA de una imagen (§16)",
)
def dna_desde_imagen(
    product_id: uuid.UUID,
    session: SessionDep,
    imagen: Annotated[UploadFile, File(description="Foto o ficha del producto")],
) -> DnaExtraido:
    """La imagen del primer eslabón del §48: «ficha técnica + imagen»."""
    producto = _producto(session, product_id)

    datos = imagen.file.read()
    if not datos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "la imagen llegó vacía")
    if len(datos) > MAXIMO_IMAGEN_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"la imagen pesa {len(datos)} bytes y el máximo son {MAXIMO_IMAGEN_BYTES}",
        )

    tipo = imagen.content_type or "application/octet-stream"
    if tipo not in MEDIA_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"{tipo} no es una imagen que el proveedor acepte; "
            f"admitidos: {', '.join(sorted(MEDIA_TYPES))}",
        )

    nombre = imagen.filename or "imagen"
    crudo = _guardar_crudo(product_id, datos, nombre)
    # `text` vacío y no la descripción del producto: lo que se le pide al
    # modelo es que lea LA IMAGEN. Colarle el texto que ya teníamos le dejaría
    # repetirlo como si lo hubiera visto en la foto.
    return _extraer_y_guardar(
        session,
        producto,
        crudo=crudo,
        documento=SourceDocument(text="", kind="image", reference=crudo.minio_key),
        nombre=nombre,
        # `cast` por lo mismo que en `apps/evaluacion/hs_accuracy.py`: el
        # protocolo declara `name` como variable de instancia y los proveedores
        # la traen de clase. Es estructuralmente compatible.
        nuevo_extractor=lambda: VisionExtractor(
            cast("ModelProvider", get_default_provider()), image=datos, media_type=tipo
        ),
    )


@router.post(
    "/{product_id}/classify",
    status_code=status.HTTP_201_CREATED,
    summary="Clasifica el producto y persiste la decisión",
)
def clasificar(
    product_id: uuid.UUID, peticion: ClassifyRequest, session: SessionDep
) -> ClassifyResponse:
    """Corre el motor sobre el Product DNA vigente y guarda el resultado.

    Es el único endpoint que escribe. Todo lo demás lee, y por eso este lleva
    el commit explícito: la sesión no confirma por su cuenta.

    Nunca devuelve 500 por no poder clasificar. Un `INSUFFICIENT_INFORMATION`
    con su razón es un resultado legítimo y se persiste igual: saber que el
    sistema no pudo, y por qué, vale tanto como el código cuando sí puede.
    """
    if session.get(Product, product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "producto no encontrado")

    dna_fila = version_vigente(session, product_id)
    if dna_fila is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "el producto no tiene Product DNA vigente: primero hay que extraerlo",
        )

    borrador = cargar_borrador(session, product_id)
    assert borrador is not None  # `version_vigente` ya garantizó que existe

    # La tubería vive en `apps.api.clasificacion` para que el harness de
    # evaluación mida EXACTAMENTE este camino, no una copia que se desvíe.
    clasificado = clasificar_borrador(
        session,
        borrador,
        operation_date=peticion.operation_date,
        trade_flow=peticion.trade_flow,
        search_terms=peticion.search_terms or None,
    )
    outcome = clasificado.outcome
    legal_refs = clasificado.legal_refs
    hay_notas = clasificado.hay_notas
    uso_vectores = clasificado.uso_vectores
    embedder = clasificado.embedder

    decision = save_classification(
        session,
        outcome,
        product_id=product_id,
        product_dna_id=dna_fila.id,
        trade_flow=peticion.trade_flow,
    )
    session.commit()

    return ClassifyResponse(
        decision_id=decision.id,
        status=outcome.status.value,
        fraction_code=outcome.code,
        nico_code=outcome.nico,
        nico_motivo=outcome.nico_reason if outcome.code else None,
        confidence=outcome.trace.confidence,
        requires_human_review=decision.requires_human_review,
        trace_steps=len(outcome.trace.steps),
        legal_refs_used=len(legal_refs),
        classified_without_legal_notes=not hay_notas,
        blocked_by=outcome.blocked_by,
        modo_busqueda=MODO_SEMANTICO if uso_vectores else MODO_TERMINO,
        degradado_por=None if uso_vectores else _porque_no_vectores(embedder),
    )
