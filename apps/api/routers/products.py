"""Lectura de productos y su Product DNA (§16).

Sólo lectura. La escritura la hará el orquestador cuando persista lo que
produce el Product DNA Engine; exponerla aquí antes invitaría a saltarse el
motor y a escribir atributos sin estado ni evidencia.

Los esquemas salen de `schemas/`, tal cual los definió Persona 2. No se
declaran formas nuevas: si un campo faltara, se acuerda con él en vez de
inventar una variante que después no cuadre con la tabla.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, cast

import sqlalchemy as sa
from core.llm.errors import ProviderNotConfiguredError, ProviderResponseError
from core.llm.registry import get_default_provider
from core.product_dna.types import SourceDocument
from core.product_dna.vision import MEDIA_TYPES, VisionExtractor
from database.models import Product, ProductAttribute, ProductDna
from database.repositories import save_classification
from database.repositories.product_dna import guardar_dna
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from ingestion.snice.raw import content_hash, local_target, store_raw_bytes
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

if TYPE_CHECKING:
    from core.llm.base import ModelProvider
from apps.api.dna import cargar_borrador, version_vigente

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


#: Lo más grande que se acepta subir. No es una cifra de rendimiento: una
#: imagen de más de esto casi nunca es una foto de producto, y el proveedor de
#: visión la rechazaría después de habernos costado el viaje.
MAXIMO_IMAGEN_BYTES = 8 * 1024 * 1024


class DnaDesdeImagenResponse(BaseModel):
    """Lo que se extrajo de la imagen, y de dónde salió."""

    product_dna_id: uuid.UUID
    version: int
    atributos: int
    summary: str | None = None
    missing_information: list[str] = Field(default_factory=list)

    minio_key: str
    """Dónde quedó el crudo. Sin esto no se puede volver a la imagen."""
    content_hash: str
    """El hash del archivo TAL COMO SE RECIBIÓ. Es lo que prueba, meses
    después, que el atributo salió de esa foto y no de otra."""


@router.post(
    "/{product_id}/dna/from-image",
    status_code=status.HTTP_201_CREATED,
    summary="Extrae el Product DNA de una imagen (§16)",
)
def dna_desde_imagen(
    product_id: uuid.UUID,
    session: SessionDep,
    imagen: Annotated[UploadFile, File(description="Foto o ficha del producto")],
) -> DnaDesdeImagenResponse:
    """Cierra el primer eslabón del §48: «usuario carga ficha técnica + imagen».

    EL CRUDO SE GUARDA ANTES DE MIRARLO (§12, regla 7)

    La imagen sube a MinIO con su `content_hash` ANTES de pasar por el modelo.
    Si el orden fuera el otro, un fallo del proveedor dejaría atributos sin
    documento del que dijeran venir, y esa es exactamente la situación que el
    pipeline existe para que no ocurra: lo único irreversible es el crudo.

    EL ORIGEN LO HEREDA DEL PRODUCTO

    El DNA de un producto sintético es `SYNTHETIC` aunque la foto sea real y el
    modelo real. Inventar un sexto valor para «lo que subió un usuario»
    rompería los cinco cerrados del §9, y el dato que describe no cambia de
    naturaleza por cómo se extrajo.
    """
    producto = session.get(Product, product_id)
    if producto is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "producto no encontrado")

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

    capture = store_raw_bytes(
        datos,
        source_url=f"upload://producto/{product_id}/{imagen.filename or 'imagen'}",
        minio_key=f"product-dna/{product_id}/{content_hash(datos)}",
        target=local_target(),
    )

    try:
        # `cast` por lo mismo que en `apps/evaluacion/hs_accuracy.py`: el
        # protocolo declara `name` como variable de instancia y los
        # proveedores la traen de clase. Es estructuralmente compatible.
        extractor = VisionExtractor(
            cast("ModelProvider", get_default_provider()), image=datos, media_type=tipo
        )
        # `text` vacío y no la descripción del producto: lo que se le pide al
        # modelo es que lea LA IMAGEN. Colarle el texto que ya teníamos le
        # dejaría repetirlo como si lo hubiera visto en la foto.
        borrador = extractor.extract(
            SourceDocument(text="", kind="image", reference=capture.minio_key)
        )
    except ProviderNotConfiguredError as exc:
        # El crudo YA está guardado y eso no se deshace: la imagen existe y su
        # hash consta, aunque no hayamos podido leerla. Se dice cuál falta.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"no hay proveedor de visión configurado: {exc}",
        ) from exc
    except ProviderResponseError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"el proveedor de visión no devolvió algo utilizable: {exc}",
        ) from exc

    dna = guardar_dna(
        session,
        borrador,
        product_id=product_id,
        data_origin=producto.data_origin,
        telemetria=extractor.last_metadata,
    )
    session.commit()

    return DnaDesdeImagenResponse(
        product_dna_id=dna.id,
        version=dna.version,
        atributos=len(borrador.attributes),
        summary=borrador.summary,
        missing_information=list(borrador.missing_information),
        minio_key=capture.minio_key,
        content_hash=capture.content_hash,
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
        confidence=outcome.trace.confidence,
        requires_human_review=decision.requires_human_review,
        trace_steps=len(outcome.trace.steps),
        legal_refs_used=len(legal_refs),
        classified_without_legal_notes=not hay_notas,
        blocked_by=outcome.blocked_by,
        modo_busqueda=MODO_SEMANTICO if uso_vectores else MODO_TERMINO,
        degradado_por=None if uso_vectores else _porque_no_vectores(embedder),
    )
