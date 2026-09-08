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
from typing import Annotated

import sqlalchemy as sa
from database.models import Product, ProductAttribute, ProductDna
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import Field
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
