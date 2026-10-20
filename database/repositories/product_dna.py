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

from database.models.intelligence import EvidenceRecord, ProductAttribute, ProductDna

if TYPE_CHECKING:
    import uuid

    from core.evidence.types import Evidence
    from core.llm.types import CallMetadata
    from core.product_dna.types import ProductDnaDraft
    from sqlalchemy.orm import Session


def guardar_dna(
    session: Session,
    borrador: ProductDnaDraft,
    *,
    product_id: uuid.UUID,
    data_origin: str,
    evidencia: Evidence | None = None,
    telemetria: CallMetadata | None = None,
) -> ProductDna:
    """Escribe una versión nueva del DNA de un producto. NO hace commit.

    El commit lo controla quien llama, por lo mismo que en `save_classification`:
    extraer un DNA casi nunca es el único efecto de la petición.

    `data_origin` lo decide el llamante y normalmente es el del PRODUCTO: el
    DNA de un producto sintético es sintético, por mucho que lo haya extraído
    un modelo de una imagen real. Inventar aquí un origen nuevo para «lo que
    subió un usuario» rompería los cinco valores cerrados del §9.

    LA FICHA Y CADA ATRIBUTO APUNTAN A SU EVIDENCIA (13-oct)

    `evidencia` es la de la extracción: `MODEL_OUTPUT`, con el hash y la clave
    de MinIO del crudo. Se escribe una sola vez y la ficha (`evidence_id`) y
    cada atributo (`evidence_reference`) apuntan a ella; el `locator` de cada
    atributo dice en qué parte de ese documento está el dato. Hasta ahora las
    fichas que salían de imagen no enlazaban nada, y el localizador que el
    motor exige se perdía al guardar.
    """
    anterior = session.scalar(
        sa.select(sa.func.max(ProductDna.version)).where(ProductDna.product_id == product_id)
    )

    # UNA EXTRACCIÓN VACÍA NO DESPLAZA A LA ANTERIOR
    #
    # Pasó en vivo: Persona 1 subió una imagen que el modelo no supo leer, el
    # DNA nuevo entró con cero atributos como vigente, y el motor dejó de poder
    # clasificar ese producto — «no hay términos de nomenclatura con los que
    # buscar». Un borrador sin nada que aportar no es una versión mejor: es
    # ninguna versión, y pisar con él lo que sí servía destruye información.
    #
    # Se guarda igual, con su número y su trazabilidad, porque el intento
    # ocurrió y consta. Lo que no hace es quedarse como vigente.
    #
    # Se miran los atributos CONOCIDOS, no todos: el motor devuelve siempre el
    # catálogo completo del §16, con lo que no encontró en MISSING. Contar esos
    # haría que una lectura vacía «aportara» 18 atributos.
    aporta = bool(borrador.known())
    if aporta:
        session.execute(
            sa.update(ProductDna)
            .where(ProductDna.product_id == product_id, ProductDna.is_current.is_(True))
            .values(is_current=False)
        )

    registro = _guardar_evidencia(session, evidencia, data_origin) if evidencia else None
    evidence_id = registro.id if registro else None

    dna = ProductDna(
        product_id=product_id,
        version=(anterior or 0) + 1,
        is_current=aporta,
        input_kinds=list(borrador.input_kinds),
        summary=borrador.summary,
        missing_information=list(borrador.missing_information),
        data_origin=data_origin,
        evidence_id=evidence_id,
        **_telemetria(telemetria),
    )
    session.add(dna)
    session.flush()
    if registro is not None:
        registro.subject_id = dna.id

    for atributo in borrador.attributes:
        session.add(
            ProductAttribute(
                product_dna_id=dna.id,
                name=atributo.name,
                value=atributo.value,
                unit=atributo.unit,
                status=atributo.status,
                confidence=atributo.confidence,
                # Sólo lo que salió del documento apunta a él. Un MISSING no
                # salió de ningún sitio: enlazarlo diría que el archivo lo
                # respalda.
                evidence_reference=evidence_id if atributo.is_known else None,
                locator=atributo.locator,
                data_origin=data_origin,
            )
        )
    session.flush()
    return dna


def _guardar_evidencia(session: Session, evidencia: Evidence, data_origin: str) -> EvidenceRecord:
    """La fila de la evidencia de la extracción, antes que la ficha que la cita.

    `subject_id` se rellena después, cuando la ficha ya tiene id: el vínculo es
    blando a propósito (ver `EvidenceRecord`) y aquí la evidencia nace primero.
    """
    campos = evidencia.to_record_fields()
    origen = campos.pop("data_origin", None) or data_origin
    fila = EvidenceRecord(subject_kind="product_dna", data_origin=origen, **campos)
    session.add(fila)
    session.flush()
    return fila


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
