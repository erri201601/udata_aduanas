"""Puente de vocabulario entre la ficha técnica y la tarifa (§18).

NO ES FUNDAMENTO JURÍDICO Y NO PUEDE CITARSE COMO TAL

Es lo que el §18 ya permite hacer a un modelo —traducir «laptop gamer» a
«máquina automática para tratamiento de datos»— escrito de forma determinista
y auditable en vez de dejado a una salida de LLM. La decisión se sigue
sosteniendo en el texto de la tarifa; el puente sólo ayuda a encontrarlo.

TODOS ENTRAN COMO `SYNTHETIC`, Y ESO IMPORTA

Los escribimos nosotros a partir de los textos reales de la LIGIE, pero
NADIE con licencia los ha validado. Mientras eso siga así son conjetura
nuestra marcada como tal (§10), y la traza de cualquier decisión que los use
lo dice. El día que un clasificador los revise pasan a `HUMAN_VALIDATED` —y
ese cambio de una columna es toda la diferencia entre una suposición y
criterio profesional.

CADA UNO LLEVA POR QUÉ

`note` no es documentación: es lo que lee quien audite la decisión y quiera
saber si el puente era legítimo. Un sinónimo sin explicación no se puede
discutir, y uno que no se puede discutir no se puede corregir.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from database.models import NomenclatureSynonym

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = structlog.stdlib.get_logger("ingestion.sintetico.sinonimos")

FUENTE: Final[str] = "UDATA — vocabulario de apoyo, sin validar por clasificador"

#: (como lo dice la ficha, como lo dice la tarifa, por qué).
#:
#: Deliberadamente corto. Cada entrada de más es una forma nueva de llevar al
#: motor por una vía que nadie leyó en el documento, y el coste de un puente
#: equivocado es una fracción equivocada.
PUENTES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "conduccion",
        "oleoductos",
        "Una tubería «para conducción de fluidos» es, en la práctica aduanera, "
        "de los tipos utilizados en oleoductos o gasoductos. NO es automático: "
        "un tubo de agua potable también conduce fluidos y no cae ahí. "
        "Necesita validación de un clasificador.",
    ),
    (
        "fluidos",
        "gasoductos",
        "Mismo puente que «conducción». Se incluye el término hermano porque la "
        "tarifa nombra los dos y una ficha suele decir sólo «fluidos».",
    ),
    (
        "izado",
        "eslingas",
        "Un cable «para izado y manipulación de cargas» es lo que la partida "
        "7312 llama cables, trenzas y eslingas. La ficha habla del uso; la "
        "tarifa, del artículo.",
    ),
    (
        "limpieza",
        "esponjas",
        "Un estropajo «para limpieza doméstica» cae en la partida que la tarifa "
        "describe como esponjas, estropajos y artículos similares.",
    ),
    (
        "vajilla",
        "mesa",
        "Una vajilla es, para la tarifa, un artículo «para el servicio de mesa "
        "o cocina». La ficha dice el objeto; la tarifa, su función.",
    ),
    (
        "galvanizado",
        "recubrimiento",
        "Galvanizar es aplicar un recubrimiento de zinc. La tarifa distingue "
        "«con recubrimiento» de «sin recubrimiento» y una ficha dice sólo "
        "«galvanizado».",
    ),
)


def cargar(session: Session, *, on_date: date | None = None) -> int:
    """Escribe los puentes que falten. Idempotente: no duplica.

    Devuelve cuántos se crearon. Cero significa que ya estaban todos, no que
    algo falló.
    """
    vigencia = on_date or date(2026, 1, 1)
    creados = 0

    for comercial, nomenclatura, nota in PUENTES:
        existe = session.scalar(
            sa.select(NomenclatureSynonym.id).where(
                NomenclatureSynonym.commercial_term == comercial,
                NomenclatureSynonym.nomenclature_term == nomenclatura,
                NomenclatureSynonym.valid_from == vigencia,
            )
        )
        if existe:
            continue
        session.add(
            NomenclatureSynonym(
                commercial_term=comercial,
                nomenclature_term=nomenclatura,
                note=nota,
                # SYNTHETIC mientras nadie con licencia los valide. No es una
                # formalidad: es lo que impide que una conjetura nuestra se
                # presente con el mismo peso que la LIGIE.
                data_origin="SYNTHETIC",
                valid_from=vigencia,
                source_url=FUENTE,
                source_document=FUENTE,
                content_hash=f"sinonimo:{comercial}:{nomenclatura}",
                retrieved_at=datetime.now(UTC),
            )
        )
        creados += 1

    session.flush()
    log.info("sinonimos.cargados", creados=creados, totales=len(PUENTES))
    return creados
