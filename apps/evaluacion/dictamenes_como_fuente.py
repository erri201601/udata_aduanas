"""Los dictámenes humanos como fuente de casos. La única que mide precisión.

QUÉ CAMBIA RESPECTO AL CORPUS

El corpus espejo compara contra una verdad que decidió un modelo, así que su
número es coincidencia con otro modelo. Aquí la verdad la firmó una persona
revisando el caso, y por eso estos casos salen con `verdad_de_modelo=False`:
es la diferencia entre medir precisión y medir parecido.

Hoy esta fuente devuelve CERO casos, y eso es correcto: no hay ningún
dictamen todavía. Existe para que el día que llegue el primero no haya que
escribir nada, y para que se vea qué le falta al sistema para medirse de
verdad.

LO QUE ESTE NÚMERO TAMPOCO DIRÁ, Y HAY QUE DECIRLO ANTES

Los dictámenes salen de la bandeja de revisión, y a la bandeja llegan los
casos que el motor NO pudo resolver o que pidió mirar. Así que esta fuente
mide al motor sobre una MUESTRA SESGADA: justo donde ya se sabía que flaquea.
Un 40 % aquí no es el 40 % del sistema — es el 40 % de lo difícil.

Se arregla cuando alguien dictamine también casos que el motor resolvió
limpio, que es lo que el endpoint de revisión ya permite a propósito («una
decisión resuelta limpia, que nunca estuvo en la bandeja, SÍ puede revisarse:
es lo que hace falta para muestrear lo que la bandeja deja pasar»). Mientras
eso no pase, el sesgo va escrito en el reporte.

LA MERCANCÍA SIGUE SIENDO SINTÉTICA

El juicio es humano; los productos del corpus no. Por eso el caso conserva el
`data_origin` de la MERCANCÍA y no el del dictamen: si dijera
`HUMAN_VALIDATED`, el reporte dejaría de avisar de que esto no es una
medición de producción (§33), y eso sería mentir por omisión.

NO SE LEE LO QUE DIJO LA MÁQUINA

Al motor sólo le llega la descripción, igual que en las otras fuentes. El
dictamen aporta la respuesta esperada, nunca la pregunta.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from core.evaluation.harness import CasoDeEvaluacion
from database.models import ClassificationDecision, Product, ProductDna

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

log = structlog.stdlib.get_logger("apps.evaluacion.dictamenes")

#: Lo que marca a una decisión como veredicto de una persona (§9).
DICTAMEN: Final = "HUMAN_VALIDATED"

#: La nomenclatura real. Igual que el corpus: son fracciones de la TIGIE, y lo
#: que hace válida la comparación es `mismo_catalogo_a_la_fecha`, no afirmar
#: ninguna edición del Sistema Armonizado. El porqué está en el harness.
NOMENCLATURA: Final = "TIGIE"


class DictamenesHumanos:
    """`FuenteDeCasos` sobre los veredictos humanos, sin escribir nada."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.nombre = "DICTAMENES_HUMANOS"

    def casos(self) -> Iterator[CasoDeEvaluacion]:
        filas = self._session.execute(
            sa.select(
                ClassificationDecision.id,
                ClassificationDecision.fraction_code,
                ClassificationDecision.operation_date,
                ProductDna.summary,
                Product.data_origin,
            )
            .join(ProductDna, ProductDna.id == ClassificationDecision.product_dna_id)
            .join(Product, Product.id == ProductDna.product_id)
            .where(ClassificationDecision.data_origin == DICTAMEN)
            .order_by(ClassificationDecision.operation_date, ClassificationDecision.id)
        ).all()

        sin_fraccion = 0
        entregados = 0
        for f in filas:
            if not f.fraction_code or not f.summary:
                # Un dictamen puede confirmar que NO se puede clasificar. Eso es
                # un juicio válido y no mide precisión de clasificación: no hay
                # código contra el que comparar. Se cuenta y se omite.
                sin_fraccion += 1
                continue

            entregados += 1
            yield CasoDeEvaluacion(
                identificador=str(f.id),
                descripcion=f.summary,
                hs6_esperado=str(f.fraction_code)[:6],
                fecha=f.operation_date,
                fuente=self.nombre,
                nomenclatura=NOMENCLATURA,
                # De la MERCANCÍA, no del dictamen: el juicio es humano, el
                # producto sigue siendo sintético.
                data_origin=f.data_origin,
                # Lo decidió una persona. Esto es lo que convierte la medición
                # en precisión y no en coincidencia.
                verdad_de_modelo=False,
                mismo_catalogo_a_la_fecha=True,
            )

        log.info(
            "dictamenes.casos",
            dictamenes=len(filas),
            casos=entregados,
            sin_fraccion=sin_fraccion,
        )
