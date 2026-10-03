"""Entradas del RGI Engine.

El motor no recibe un `ProductDna` de SQLAlchemy: recibe hechos. Así se puede
evaluar un producto que todavía no está persistido, y `core/` no depende de la
capa de datos (§29).

Quien tenga un `ProductDna` construye un `ClassificationContext` desde él; esa
traducción vive fuera del motor, en el orquestador.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProductFact(BaseModel):
    """Un atributo del producto, con de dónde salió.

    `status` replica los cuatro estados de §16 del maestro. El motor los trata
    distinto a propósito: un hecho `INFERRED` puede sugerir una vía, pero no
    debería ser lo único que sostenga una clasificación. Un dato deducido por
    un modelo y uno leído de una ficha técnica no pesan igual.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    value: str | None = None
    status: str = "MISSING"
    """OBSERVED | EXTRACTED | INFERRED | MISSING (§16)."""
    confidence: Decimal | None = None

    @property
    def is_known(self) -> bool:
        """¿Aporta información? `MISSING` y los valores vacíos, no."""
        return self.status != "MISSING" and bool(self.value and self.value.strip())

    @property
    def is_solid(self) -> bool:
        """¿Se puede sostener una clasificación sobre este hecho?

        Sólo lo observado o extraído del documento. Lo inferido acompaña pero
        no sostiene.
        """
        return self.is_known and self.status in ("OBSERVED", "EXTRACTED")


class TariffCandidate(BaseModel):
    """Una posición de la nomenclatura que podría corresponder.

    `code` va como texto, nunca entero: los ceros a la izquierda son
    significativos y `08471301` no es lo mismo que `8471301`.
    """

    model_config = ConfigDict(frozen=True)

    code: str
    text: str
    """Texto literal de la partida, subpartida o fracción."""
    level: str
    """CHAPTER | HEADING | SUBHEADING | FRACTION | NICO."""
    source_id: Any | None = None
    """Identificador de la fuente que respalda este texto. Lo necesita el
    Evidence Contract para poder citarla."""
    specificity: int = 0
    """Qué tan específico es el texto respecto de la mercancía. Lo usa la
    RGI 3 a). Mayor es más específico."""

    group_text: str | None = None
    """El encabezado de un guion bajo el que cuelga esta posición (ADR 0004).

    La LIGIE agrupa subpartidas hermanas bajo una línea sin código —«Los demás
    monitores:», «Proyectores:»— y ESE es su discriminador propio: las nueve
    subpartidas de 8528 dicen casi lo mismo y sólo el encabezado las separa.

    Va aparte de `text` y no sustituye a nada. El grupo no es un candidato —no
    tiene código y devolverlo como tal rompería el contrato—, pero sí es un
    dato DE este candidato, y es el único que permite elegir entre hermanas sin
    inventar.
    """

    @property
    def chapter(self) -> str:
        """Los dos primeros dígitos."""
        return self.code[:2]

    @property
    def heading(self) -> str:
        """Los cuatro primeros dígitos."""
        return self.code[:4]


class ClassificationContext(BaseModel):
    """Todo lo que el motor necesita saber para evaluar.

    `operation_date` no tiene valor por defecto a propósito. Sin fecha no se
    puede saber qué tarifa ni qué notas aplicaban, y poner `today()` por
    omisión sería justo el error que el §14 prohíbe: evaluar una operación
    histórica con regulación posterior.
    """

    model_config = ConfigDict(frozen=True)

    description: str
    """Descripción comercial de la mercancía, tal como viene del documento."""

    operation_date: date
    facts: tuple[ProductFact, ...] = ()
    trade_flow: str = "IMPORT"
    country_of_origin: str | None = None
    search_terms: tuple[str, ...] = ()
    """Términos de nomenclatura para buscar. Si vienen vacíos y hay un
    `Interpreter`, el motor se los pide a él."""

    exclusiones: tuple[tuple[str, str], ...] = ()
    """Parejas (lo que dice la ficha, lo que exige la tarifa) que NO son lo mismo.

    Las contesta un clasificador y se guardan firmadas. Es el puente que ningún
    algoritmo puede deducir: «HFW» y «arco sumergido» no comparten ni una letra
    y no están unidas en ningún documento — sólo en la cabeza de quien clasifica.

    Con ellas el motor DESCARTA, nunca elige: una posición que exige arco
    sumergido es imposible para una mercancía que consta soldada con HFW. Eso
    deja dos candidatas en vez de nueve, y lo que quede lo decide una persona
    igual que antes.
    """

    notes: dict[str, Any] = Field(default_factory=dict)

    def fact(self, name: str) -> ProductFact | None:
        """Busca un hecho por nombre."""
        return next((f for f in self.facts if f.name == name), None)

    def known_facts(self) -> tuple[ProductFact, ...]:
        """Los hechos que aportan información."""
        return tuple(f for f in self.facts if f.is_known)

    def missing_facts(self) -> tuple[str, ...]:
        """Nombres de los atributos ausentes.

        Es lo que se le pide al importador cuando el motor devuelve
        `INSUFFICIENT_INFORMATION`, así que tiene que ser accionable: nombres
        de atributos, no una disculpa genérica.
        """
        return tuple(f.name for f in self.facts if not f.is_known)

    def as_input_facts(self) -> dict[str, str]:
        """Los hechos conocidos, para dejarlos en el `RGIResult`.

        Sin esto no se puede responder "¿qué dato utilizaste?" del §49.
        """
        return {f.name: f.value or "" for f in self.known_facts()}
