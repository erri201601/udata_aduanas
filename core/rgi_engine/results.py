"""Resultado de evaluar una regla, y de la secuencia completa.

Los campos son los que exige §18 del maestro. La razón de que sean tantos es
que un `RGIResult` tiene que poder defenderse solo: quien lo lea seis meses
después debe ver qué regla se aplicó, con qué hechos, contra qué fuentes y con
cuánta confianza — sin volver a ejecutar nada.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.rgi_engine.context import TariffCandidate
from core.rgi_engine.pregunta import Pregunta
from core.rgi_engine.states import TERMINAL, RGIStatus

#: De dónde sale un descarte. Cuatro valores y no texto libre: quien lea la
#: traza —una persona o una pantalla— tiene que poder distinguir un descarte
#: que se sostiene en el texto legal de uno que se sostiene en la firma de un
#: clasificador, sin parsear la frase.
PorQueSeDescarto = Literal["NOTA_LEGAL", "MATERIA", "CONTRADICCION", "RESPUESTA_FIRMADA"]


class Descarte(BaseModel):
    """Una posición que el motor tiene por IMPOSIBLE para esta mercancía, y por qué.

    POR QUÉ ES UN CAMPO Y NO UNA FRASE

    El motor ya decía «descartadas: 73121008: la ficha dice «6x36», que no es
    «constituidos por 7 alambres»», pero sólo dentro de `reasoning_summary`,
    que es texto para personas y cambia de redacción. Ninguna máquina podía
    leerlo sin parsear prosa, así que nadie lo leía.

    Y hacía falta. El 6-oct un clasificador dio un veredicto con 73121008 en
    «fracción correcta» mientras su propia nota explicaba que esa posición era
    incompatible: estaba describiendo el error del motor y pegó el código de
    ahí. La decisión vigente en ese momento ya la había descartado con ese
    mismo motivo. Un aviso lo habría parado, y el aviso necesita esto.

    LO QUE NO ES UN DESCARTE

    Que una regla PREFIERA otra posición —la RGI 3 a) por especificidad, un
    desempate— no hace imposible a la perdedora: un clasificador puede elegirla
    con razón. Aquí sólo entra lo que el motor afirma que la mercancía NO
    puede ser: una nota legal que la excluye, una materia que la tarifa opone,
    un texto que la ficha contradice o una respuesta firmada.

    Tampoco las candidatas de una abstención: si el motor no eligió entre tres
    fracciones viables, ninguna está descartada, y un aviso sobre ellas
    saltaría en cada veredicto hasta que nadie lo leyera.
    """

    model_config = ConfigDict(frozen=True)

    code: str
    """Al nivel en que se descartó: partida (4), subpartida (6) o fracción (8).
    Una fracción tecleada que EMPIEZA por el código de una partida descartada
    también está descartada."""

    motivo: str
    """Por qué, citable tal cual: «la ficha dice «6x36», que no es
    «constituidos por 7 alambres»»."""

    por: PorQueSeDescarto


class RGIResult(BaseModel):
    """Lo que devuelve una regla al evaluarse."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    """'RGI-1', 'RGI-3a', 'RGI-6'…"""

    status: RGIStatus
    input_facts: dict[str, str] = Field(default_factory=dict)
    candidate_codes: tuple[TariffCandidate, ...] = ()
    reasoning_summary: str = ""
    source_ids: tuple[Any, ...] = ()
    confidence: Decimal | None = None
    missing_information: tuple[str, ...] = ()

    descartadas: tuple[Descarte, ...] = ()
    """Lo que esta regla tiene por imposible, con el motivo. Ver `Descarte`."""

    preguntas: tuple[Pregunta, ...] = ()
    """Lo que haría falta saber para desatascar, en forma de sí o no.

    Vacío cuando no hay una pregunta corta que lo resuelva —muchas candidatas,
    o falta un dato en vez de un puente de vocabulario—. Entonces la respuesta
    honesta sigue siendo mandarlo a un clasificador sin acotar.
    """

    requires_human_review: bool = False
    """La regla resolvió, pero su resolución necesita que alguien la mire.

    No es lo mismo que no resolver. Un desempate de último recurso —la RGI
    3 c), «la última por orden de numeración»— produce un código válido y
    aplica la regla correctamente, y aun así no distingue nada: entre una
    computadora y un monitor elige el monitor porque 8528 va después de 8471.

    Existe como campo, y no como una comprobación del `rule_id` en la traza,
    porque quien sabe si su resolución es sustantiva es la propia regla.
    Cualquier regla futura que resuelva sin una razón de fondo lo declara
    aquí y el resto del sistema lo respeta sin tener que conocerla.
    """

    @property
    def is_terminal(self) -> bool:
        """¿Detiene la secuencia?"""
        return self.status in TERMINAL

    @property
    def resolved_code(self) -> str | None:
        """El código, sólo si la regla resolvió con un único candidato.

        Devuelve `None` con dos candidatos aunque el estado sea `RESOLVED`:
        una resolución ambigua no es una resolución.
        """
        if self.status is not RGIStatus.RESOLVED or len(self.candidate_codes) != 1:
            return None
        return self.candidate_codes[0].code


class ClassificationTrace(BaseModel):
    """La secuencia completa: qué se evaluó, en qué orden y con qué resultado.

    Es lo que hace auditable al motor. Un prompt monolítico produciría el mismo
    código final sin poder mostrar por qué se descartó cada alternativa, y ese
    "por qué" es justo lo que se defiende ante una auditoría (§18).
    """

    model_config = ConfigDict(frozen=True)

    steps: tuple[RGIResult, ...] = ()
    final_status: RGIStatus = RGIStatus.INSUFFICIENT_INFORMATION
    resolved_code: str | None = None
    confidence: Decimal | None = None
    missing_information: tuple[str, ...] = ()
    engine_version: str = "0.1.0"

    @property
    def applied_rule(self) -> str | None:
        """Qué regla resolvió. Responde "¿con qué regla?" del §49."""
        return self.steps[-1].rule_id if self.steps else None

    @property
    def requires_human_review(self) -> bool:
        """¿Necesita que alguien lo mire?

        Todo lo que no sea una resolución limpia, MÁS las resoluciones que la
        propia regla marcó como no sustantivas. El sistema falla hacia la
        cautela, igual que el default de la base.

        La segunda mitad no estaba y hacía falta: la RGI 3 c) escribía
        «conviene revisión humana» en su `reasoning_summary` y la traza no la
        escuchaba, porque sólo miraba el estado final. Una clasificación
        desempatada por orden de numeración salía `RESOLVED` y sin marcar —
        una computadora declarada como monitor, con apariencia de resuelta.
        Es el fallo que el §36 llama por su nombre: un resultado equivocado
        que parece fundado.
        """
        if self.final_status is not RGIStatus.RESOLVED or self.resolved_code is None:
            return True
        return any(paso.requires_human_review for paso in self.steps)

    def rejected(self) -> tuple[str, ...]:
        """Por qué se descartó cada regla anterior a la que resolvió.

        Lo más valioso de la traza para quien audita: no es que el sistema
        eligiera 8471.30.01, es que descartó las alternativas por un motivo
        que se puede leer.
        """
        return tuple(
            f"{p.rule_id}: {p.reasoning_summary}"
            for p in self.steps
            if p.status is RGIStatus.CONTINUE and p.reasoning_summary
        )
