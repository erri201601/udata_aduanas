"""Persistir un `ProductDnaDraft`: de lo que devuelve el motor a filas.

No existía. Los 181 Product DNA de la base los escribió el cargador del corpus
sintético directamente (`ingestion/sintetico/load.py`), y ese código no sirve
para lo que llega por la API: crea el producto y el DNA a la vez, con el
escenario y la semilla del corpus.

Aquí sólo se escribe el DNA de un producto QUE YA EXISTE, que es el caso de
cualquiera que suba una ficha o una foto.

SOBRE EL VERSIONADO

Un DNA nuevo no pisa al anterior: se guarda con `version` siguiente y el
anterior pasa a `is_current = False`. La versión vieja se conserva porque
puede haber decisiones de clasificación colgando de ella, y una decisión sin
el DNA sobre el que se tomó no se puede explicar (§49: «¿qué dato utilizaste?»).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from database.models.intelligence import ProductAttribute, ProductDna

if TYPE_CHECKING:
    import uuid

    from core.llm.types import CallMetadata
    from core.product_dna.types import ProductDnaDraft
    from sqlalchemy.orm import Session


def guardar_dna(
    session: Session,
    borrador: ProductDnaDraft,
    *,
    product_id: uuid.UUID,
    data_origin: str,
    evidence_id: uuid.UUID | None = None,
    telemetria: CallMetadata | None = None,
) -> ProductDna:
    """Escribe una versión nueva del DNA de un producto. NO hace commit.

    El commit lo controla quien llama, por lo mismo que en `save_classification`:
    extraer un DNA casi nunca es el único efecto de la petición.

    `data_origin` lo decide el llamante y normalmente es el del PRODUCTO: el
    DNA de un producto sintético es sintético, por mucho que lo haya extraído
    un modelo de una imagen real. Inventar aquí un origen nuevo para «lo que
    subió un usuario» rompería los cinco valores cerrados del §9.
    """
    anterior = session.scalar(
        sa.select(sa.func.max(ProductDna.version)).where(ProductDna.product_id == product_id)
    )
    session.execute(
        sa.update(ProductDna)
        .where(ProductDna.product_id == product_id, ProductDna.is_current.is_(True))
        .values(is_current=False)
    )

    dna = ProductDna(
        product_id=product_id,
        version=(anterior or 0) + 1,
        is_current=True,
        input_kinds=list(borrador.input_kinds),
        summary=borrador.summary,
        missing_information=list(borrador.missing_information),
        data_origin=data_origin,
        evidence_id=evidence_id,
        **_telemetria(telemetria),
    )
    session.add(dna)
    session.flush()

    for atributo in borrador.attributes:
        session.add(
            ProductAttribute(
                product_dna_id=dna.id,
                name=atributo.name,
                value=atributo.value,
                unit=atributo.unit,
                status=atributo.status,
                confidence=atributo.confidence,
                data_origin=data_origin,
            )
        )
    session.flush()
    return dna


def _telemetria(metadata: CallMetadata | None) -> dict[str, object]:
    """Qué modelo lo extrajo, con qué prompt y cuánto costó.

    Sin esto no se puede contestar «¿con qué regla?» del §49 para un dato que
    salió de un modelo, ni saber qué versión del prompt produjo un atributo
    dudoso cuando alguien lo discuta seis meses después.
    """
    if metadata is None:
        return {}
    return {
        "model_provider": metadata.model_provider,
        "model_name": metadata.model_name,
        "prompt_id": metadata.prompt_id,
        "prompt_version": metadata.prompt_version,
        "input_tokens": metadata.usage.input_tokens,
        "output_tokens": metadata.usage.output_tokens,
        "latency_ms": metadata.latency_ms,
        "attempts": metadata.attempts,
        "finish_reason": metadata.finish_reason,
    }
