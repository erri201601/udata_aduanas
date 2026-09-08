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
from typing import Annotated

import sqlalchemy as sa
from core.classification import classify_product
from core.product_dna import ExtractedAttribute, ProductDnaDraft
from database.models import Product, ProductAttribute, ProductDna
from database.repositories import save_classification
from database.repositories.notes import LegalNotesRepository
from database.repositories.tariff import TariffCatalogRepository
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from schemas.intelligence import ProductAttributeRead, ProductDnaRead
from schemas.operational import ProductRead

from apps.api.db import SessionDep

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

    classified_without_legal_notes: bool
    """¿Se clasificó sin notas de sección ni capítulo?

    La RGI 1 dice que la clasificación se determina por los textos de las
    partidas Y por las notas. Mientras `regulatory.legal_rules` esté vacía no
    se pueden descartar partidas por exclusión, y el resultado es menos
    fundamentado. Se declara en vez de dejar que parezca que se consultaron y
    no excluían nada.
    """

    blocked_by: str | None = None


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

    dna_fila = session.scalars(
        sa.select(ProductDna)
        .where(ProductDna.product_id == product_id, ProductDna.is_current.is_(True))
        .order_by(ProductDna.version.desc())
    ).first()
    if dna_fila is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "el producto no tiene Product DNA vigente: primero hay que extraerlo",
        )

    atributos = session.scalars(
        sa.select(ProductAttribute).where(ProductAttribute.product_dna_id == dna_fila.id)
    ).all()

    borrador = ProductDnaDraft(
        summary=dna_fila.summary,
        missing_information=tuple(dna_fila.missing_information or ()),
        input_kinds=tuple(dna_fila.input_kinds or ()),
        attributes=tuple(
            ExtractedAttribute(
                name=a.name,
                value=a.value,
                unit=a.unit,
                status=a.status,  # type: ignore[arg-type]
                confidence=a.confidence,
                # `locator` no se persiste: los estados ya vienen saneados de
                # cuando se extrajo, así que rehacer el saneamiento aquí los
                # degradaría una segunda vez sin motivo.
                locator=a.value,
            )
            for a in atributos
        ),
    )

    notas = LegalNotesRepository(session)
    hay_notas = notas.hay_corpus(on_date=peticion.operation_date)

    outcome = classify_product(
        borrador,
        operation_date=peticion.operation_date,
        catalog=TariffCatalogRepository(session),
        notes=notas,
        search_terms=peticion.search_terms or _terminos(borrador),
        trade_flow=peticion.trade_flow,
    )

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
        classified_without_legal_notes=not hay_notas,
        blocked_by=outcome.blocked_by,
    )


def _terminos(dna: ProductDnaDraft) -> list[str]:
    """Términos de búsqueda a partir de lo sólido del Product DNA.

    Sólo lo observado o extraído: buscar en la nomenclatura con un dato
    inferido llevaría al motor por una vía que nadie leyó en el documento.
    """
    terminos = [a.value for a in dna.solid() if a.value]
    if dna.summary:
        terminos.insert(0, dna.summary)
    return terminos[:6]
