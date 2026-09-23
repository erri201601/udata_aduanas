"""El corpus espejo como fuente de casos para `hs_accuracy`.

LO QUE ESTE NÚMERO VA A MEDIR, DICHO ANTES DE MEDIRLO

La clasificación esperada del corpus la decidió un modelo —salió de una sesión
de ChatGPT, sin clasificador humano en el circuito (Persona 1, 23-sep-2026)—.
Así que comparar contra ella NO mide precisión: mide COINCIDENCIA CON OTRO
MODELO. Cada caso sale marcado con `verdad_de_modelo=True` y el reporte lo
declara como su cuarto límite.

Eso no lo hace inútil. Los DESACUERDOS son lo valioso: cada uno que una persona
resuelva se convierte en verdad de campo, y ése es el único camino a medir
precisión de verdad.

Lo que sí está comprobado del corpus son sus afirmaciones contrastables —que la
fracción exista, que el NICO le pertenezca, que la tasa y la UMC sean las de la
LIGIE oficial: las ocho comprobaciones del #84 sobre 180 partidas, cero
defectos. Lo que nadie comprobó es el JUICIO de clasificación.

DE DÓNDE SALE CADA COSA, Y POR QUÉ DE POSTGRES Y NO DEL JSON

El corpus vive en MinIO, pero todo lo que un caso necesita ya está cargado:

    descripción   `ProductDna.summary` — la descripción COMERCIAL de la partida
    fecha         `Pedimento.operation_date`
    verdad        `ground_truth_records.original_value` cuando la anomalía es
                  de fracción; si no, la fracción declarada, que en esa partida
                  no se mutó
    evaluable     `ProductDna.missing_information` vacío

Leer de la base evita una credencial que no hace falta y mide lo que el motor
tiene delante, que es lo cargado, no lo que dice un fichero.

NO SE FILTRA LA RESPUESTA

Al motor sólo le llega `descripcion`. El harness excluye además cualquier caso
cuya descripción contenga el HS6 esperado (`POSIBLE_FUGA`), así que si alguna
descripción comercial trae el código, ese caso no puntúa.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
import structlog
from core.evaluation.harness import CasoDeEvaluacion
from database.models import (
    GroundTruthRecord,
    Pedimento,
    PedimentoItem,
    Product,
    ProductDna,
    SyntheticScenario,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

log = structlog.stdlib.get_logger("apps.evaluacion.corpus")

#: La nomenclatura que se declara para estos casos.
#:
#: Los seis primeros dígitos de una fracción de la TIGIE son la subpartida del
#: Sistema Armonizado. La LIGIE vigente adoptó el SA 2022 y la edición
#: siguiente no ha entrado, así que esos seis dígitos son HS2022.
#:
#: SI ESTO ESTUVIERA MAL, FALLA RUIDOSAMENTE: el harness excluiría los casos
#: con `NOMENCLATURA_NO_SA2022` y el reporte diría cero evaluados. No hay forma
#: de que produzca un número equivocado en silencio, que es la única razón por
#: la que se puede escribir aquí un supuesto sin haberlo confirmado con la
#: fuente oficial.
NOMENCLATURA: Final = "HS2022"

#: El corpus es sintético y no puede fundamentar nada (§33).
ORIGEN: Final = "SYNTHETIC"

#: La anomalía cuya verdad cambia la fracción esperada. En las demás la
#: declarada NO se mutó, así que la declarada ES la esperada.
_ANOMALIA_DE_FRACCION: Final = "WRONG_FRACTION"


class CorpusEspejo:
    """`FuenteDeCasos` sobre el corpus ya cargado, sin escribir nada.

    `solo_evaluables` deja fuera las partidas cuya ficha el corpus recortó a
    propósito. No es maquillaje: en ellas la respuesta correcta es pedir
    revisión humana, y contarlas como fallo de clasificación mediría una
    decisión del corpus. Se cuentan aparte y el motivo viaja en el log.
    """

    def __init__(
        self,
        session: Session,
        *,
        escenario: str = "corpus_espejo_v1",
        solo_evaluables: bool = True,
    ) -> None:
        self._session = session
        self._escenario = escenario
        self._solo_evaluables = solo_evaluables

    @property
    def nombre(self) -> str:
        return f"CORPUS_ESPEJO/{self._escenario}"

    def _fracciones_esperadas(self) -> dict[object, str]:
        """La verdad del corpus donde difiere de lo declarado."""
        filas = self._session.execute(
            sa.select(GroundTruthRecord.pedimento_item_id, GroundTruthRecord.original_value).where(
                GroundTruthRecord.error_type == _ANOMALIA_DE_FRACCION,
                GroundTruthRecord.pedimento_item_id.isnot(None),
                GroundTruthRecord.original_value.isnot(None),
            )
        ).all()
        return {f.pedimento_item_id: str(f.original_value) for f in filas}

    def casos(self) -> Iterator[CasoDeEvaluacion]:
        esperada_por_partida = self._fracciones_esperadas()

        filas = self._session.execute(
            sa.select(
                PedimentoItem.id,
                PedimentoItem.line_number,
                PedimentoItem.declared_fraction_code,
                Pedimento.pedimento_number,
                Pedimento.operation_date,
                ProductDna.summary,
                ProductDna.missing_information,
            )
            .join(Pedimento, Pedimento.id == PedimentoItem.pedimento_id)
            .join(SyntheticScenario, SyntheticScenario.id == Pedimento.synthetic_scenario_id)
            .join(Product, Product.id == PedimentoItem.product_id)
            .join(
                ProductDna,
                sa.and_(ProductDna.product_id == Product.id, ProductDna.is_current.is_(True)),
            )
            .where(SyntheticScenario.slug == self._escenario)
            .order_by(Pedimento.pedimento_number, PedimentoItem.line_number)
        ).all()

        omitidas = 0
        for f in filas:
            if self._solo_evaluables and f.missing_information:
                # El corpus recortó la ficha a propósito: aquí la respuesta
                # correcta es pedir revisión humana, no un código.
                omitidas += 1
                continue
            esperada = esperada_por_partida.get(f.id) or f.declared_fraction_code
            if not esperada or not f.summary:
                omitidas += 1
                continue

            yield CasoDeEvaluacion(
                identificador=f"{f.pedimento_number}/{f.line_number}",
                descripcion=f.summary,
                hs6_esperado=str(esperada)[:6],
                fecha=f.operation_date,
                fuente=self.nombre,
                nomenclatura=NOMENCLATURA,
                data_origin=ORIGEN,
                # La verdad contra la que se compara la decidió un modelo.
                verdad_de_modelo=True,
            )

        log.info("corpus.casos", escenario=self._escenario, partidas=len(filas), omitidas=omitidas)
