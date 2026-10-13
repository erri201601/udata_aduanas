"""La redacción del Copilot y la comprobación que decide si se entrega (ADR 0010).

EL MODELO EXPLICA, NO APORTA

Se le entregan sólo los pasajes que pueden fundamentar —vigentes en la fecha y
con un origen que fundamenta—, numerados. Tiene que terminar cada oración
citando `[n]`. Después, código y no otro modelo comprueba las citas:

- una cita a un `n` que no se entregó invalida la redacción ENTERA. No se
  corrige ni se recorta: si inventó una cita, nada de lo demás es fiable;
- la confianza es la proporción de oraciones con cita. La que el modelo se
  atribuye no está calibrada, y ésta se puede medir (§39).

SIN PASAJES QUE FUNDAMENTEN NO SE LLAMA AL MODELO

Y la respuesta es el texto literal del §31: «No tengo evidencia suficiente en la
base cargada.» Llamarlo igual sólo le daría la ocasión de redactar sin base.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

import structlog
from pydantic import BaseModel, Field

from core.llm import Message
from core.llm.errors import ModelProviderError
from core.prompts import load_prompt

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    from core.llm.base import ModelProvider
    from core.llm.types import CallMetadata

log = structlog.stdlib.get_logger("core.copilot")

PROMPT_ID: Final = "copilot.answer"
PROMPT_VERSION: Final = "0.1"

#: El texto literal del §31. Sin adornos ni variantes.
SIN_EVIDENCIA: Final = "No tengo evidencia suficiente en la base cargada."

#: Punto 7 del ADR: la evidencia existe, lo que falta es la redacción.
SIN_MODELO: Final = "Sin redacción: el modelo no está disponible. Los pasajes están en evidence."

CITA_INEXISTENTE: Final = "La redacción citó un pasaje que no existe; se descartó."
REDACCION_VACIA: Final = "El modelo no devolvió ninguna oración; no hay redacción que entregar."

_CENTESIMA: Final = Decimal("0.01")


@dataclass(frozen=True)
class PasajeParaRedactar:
    """Lo que se le entrega al modelo de cada pasaje: su número, su cita y su texto."""

    n: int
    cita: str
    texto: str


class _RedaccionLLM(BaseModel):
    """Salida estructurada del prompt `copilot.answer`."""

    answer: str = ""
    missing_information: list[str] = Field(default_factory=list)


# ── Oraciones y citas ────────────────────────────────────────────────────────

#: Una cita: `[2]`, o varias en el mismo corchete: `[2, 5]`.
_CITA: Final = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

#: Donde PUEDE acabar una oración: puntuación final, quizá un cierre, y espacio.
_FIN: Final = re.compile(r"[.!?][»\"')\]]*\s+")

#: Abreviaturas habituales en texto jurídico. Tras ellas un punto NO cierra la
#: oración: «el art. 54 dice…» es una sola. Sin esta lista, cada «art.» partía
#: la oración y la que quedaba sin cita bajaba la confianza sin motivo.
_ABREVIATURAS: Final = frozenset(
    {
        "art", "arts", "fr", "fracc", "frac", "núm", "num", "no", "inc", "párr",
        "parr", "lic", "sr", "sra", "dr", "p", "pp", "pág", "pag", "cfr", "vid",
        "ss", "etc", "fed", "ofic", "dof",
    }
)  # fmt: skip


def oraciones(texto: str) -> list[str]:
    """Las oraciones del texto, sin vacías.

    Un salto de línea también separa: una respuesta en viñetas son varias
    afirmaciones, y cada una tiene que llevar su cita.
    """
    salida: list[str] = []
    for linea in texto.splitlines():
        inicio = 0
        for fin in _FIN.finditer(linea):
            antes = linea[inicio : fin.start()].split()
            ultima = antes[-1].lower().rstrip(".") if antes else ""
            if ultima in _ABREVIATURAS or (len(ultima) == 1 and ultima.isalpha()):
                continue
            trozo = linea[inicio : fin.end()].strip()
            if trozo:
                salida.append(trozo)
            inicio = fin.end()
        resto = linea[inicio:].strip()
        if resto:
            salida.append(resto)
    # Una «oración» que es sólo puntuación o viñeta no afirma nada.
    return [o for o in salida if re.search(r"\w", _CITA.sub("", o))]


def _citas(texto: str) -> list[int]:
    return [int(n) for grupo in _CITA.findall(texto) for n in re.split(r"\s*,\s*", grupo)]


@dataclass(frozen=True)
class Validacion:
    """Lo que dice el código —no el modelo— de una redacción."""

    citadas: tuple[int, ...]
    """Los `n` citados que SÍ se entregaron, sin repetir y en orden de aparición."""
    inexistentes: tuple[int, ...]
    """Los `n` citados que no se entregaron. Con uno solo se descarta todo."""
    oraciones: int
    con_cita: int

    @property
    def confidence(self) -> Decimal:
        """Oraciones con cita válida ÷ oraciones, a dos decimales (ADR 0010, 4)."""
        if self.oraciones == 0:
            return Decimal("0.00")
        return (Decimal(self.con_cita) / Decimal(self.oraciones)).quantize(
            _CENTESIMA, rounding=ROUND_HALF_UP
        )


def validar(answer: str, entregados: set[int]) -> Validacion:
    """Extrae las citas y cuenta qué oraciones llevan una válida."""
    todas = _citas(answer)
    citadas = tuple(dict.fromkeys(n for n in todas if n in entregados))
    inexistentes = tuple(dict.fromkeys(n for n in todas if n not in entregados))
    partes = oraciones(answer)
    con_cita = sum(1 for o in partes if any(n in entregados for n in _citas(o)))
    return Validacion(
        citadas=citadas,
        inexistentes=inexistentes,
        oraciones=len(partes),
        con_cita=con_cita,
    )


# ── La redacción ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Redaccion:
    """El resultado de intentar redactar, ya validado."""

    answer: str
    confidence: Decimal
    citadas: tuple[int, ...] = ()
    missing_information: tuple[str, ...] = ()
    redactada: bool = False
    """¿El `answer` lo redactó el modelo en esta consulta y se entrega?"""
    sin_evidencia: bool = False
    """No hubo pasajes que fundamenten, o la redacción se descartó."""
    modelo_no_disponible: str | None = None
    """Por qué no se pudo redactar, si fue el proveedor."""
    metadata: CallMetadata | None = field(default=None, compare=False)


def _sin_evidencia(*faltantes: str, metadata: CallMetadata | None = None) -> Redaccion:
    return Redaccion(
        answer=SIN_EVIDENCIA,
        confidence=Decimal("0.00"),
        missing_information=faltantes,
        sin_evidencia=True,
        metadata=metadata,
    )


def _bloque(pasajes: Sequence[PasajeParaRedactar]) -> str:
    return "\n\n".join(f"[{p.n}] {p.cita}\n{p.texto}" for p in pasajes)


def redactar(
    pregunta: str,
    *,
    fecha: date,
    pasajes: Sequence[PasajeParaRedactar],
    proveedor: Callable[[], ModelProvider],
) -> Redaccion:
    """Redacta una respuesta citando sólo `pasajes`, o explica por qué no.

    `proveedor` es una fábrica y no un proveedor ya construido: construirlo
    puede fallar —sin llave— y ese fallo es el punto 7 del ADR, no un 500.
    """
    if not pasajes:
        log.info("copilot.sin_evidencia", motivo="ningún pasaje puede fundamentar")
        return _sin_evidencia()

    prompt = load_prompt(PROMPT_ID, PROMPT_VERSION)
    inicio = time.monotonic()
    try:
        respuesta = proveedor().generate_structured(
            [
                Message(
                    role="user",
                    content=prompt.render(
                        pregunta=pregunta, fecha=fecha.isoformat(), pasajes=_bloque(pasajes)
                    ),
                )
            ],
            _RedaccionLLM,
            prompt_id=PROMPT_ID,
            prompt_version=PROMPT_VERSION,
            temperature=0,
        )
    except ModelProviderError as exc:
        log.warning(
            "copilot.modelo_no_disponible",
            error=type(exc).__name__,
            duration_ms=int((time.monotonic() - inicio) * 1000),
        )
        return Redaccion(
            answer=SIN_MODELO,
            confidence=Decimal("0.00"),
            modelo_no_disponible=f"{type(exc).__name__}: {exc}",
        )

    metadata = respuesta.metadata
    answer = respuesta.data.answer.strip()
    validacion = validar(answer, {p.n for p in pasajes})

    log.info(
        "copilot.redaccion",
        prompt_id=PROMPT_ID,
        prompt_version=PROMPT_VERSION,
        model=metadata.model_name,
        model_provider=metadata.model_provider,
        input_tokens=metadata.usage.input_tokens,
        output_tokens=metadata.usage.output_tokens,
        duration_ms=metadata.latency_ms,
        entregados=len(pasajes),
        citadas=list(validacion.citadas),
        inexistentes=list(validacion.inexistentes),
        oraciones=validacion.oraciones,
        con_cita=validacion.con_cita,
    )

    if validacion.inexistentes:
        return _sin_evidencia(CITA_INEXISTENTE, metadata=metadata)
    if validacion.oraciones == 0:
        return _sin_evidencia(REDACCION_VACIA, metadata=metadata)

    return Redaccion(
        answer=answer,
        confidence=validacion.confidence,
        citadas=validacion.citadas,
        missing_information=tuple(
            m.strip() for m in respuesta.data.missing_information if m.strip()
        ),
        redactada=True,
        metadata=metadata,
    )


# ── Lo que se decide sin preguntarle al modelo ──────────────────────────────

#: Cómo se nombra cada instrumento en una pregunta. NO es la lista de lo que
#: falta: lo que falta sale de comparar con `corpus_consultado`, que se lee de
#: la base (ADR 0010, punto 5). Esta tabla sólo sirve para reconocer que la
#: pregunta habla de un instrumento.
INSTRUMENTOS: Final[dict[str, tuple[str, ...]]] = {
    "PROSEC": ("prosec",),
    "Regla 8ª": ("regla 8", "regla octava"),
    "cupos": ("cupo ", "cupos"),
    "NOM": ("nom-", "norma oficial mexicana", "normas oficiales mexicanas"),
    "Anexo 2.4.1": ("2.4.1",),
    "T-MEC": ("t-mec", "tmec", "usmca"),
    "cuotas compensatorias": ("cuota compensatoria", "cuotas compensatorias"),
    "RGCE": ("rgce", "reglas generales de comercio exterior"),
    "Ley Aduanera": ("ley aduanera",),
    "LIGIE": ("ligie", "tigie"),
}


def _cargado(claves: tuple[str, ...], corpus: Sequence[str]) -> bool:
    titulos = [t.lower() for t in corpus]
    return any(clave.strip() in titulo for clave in claves for titulo in titulos)


def faltantes_deterministas(
    pregunta: str, *, corpus_consultado: Sequence[str], degradado_por: str | None
) -> list[str]:
    """Lo que falta y se sabe sin preguntarle al modelo (ADR 0010, punto 5)."""
    faltan: list[str] = []
    if degradado_por:
        faltan.append(f"La búsqueda se hizo por término, no por significado: {degradado_por}.")

    texto = f" {pregunta.lower()} "
    for nombre, claves in INSTRUMENTOS.items():
        if any(clave in texto for clave in claves) and not _cargado(claves, corpus_consultado):
            faltan.append(
                f"La pregunta nombra {nombre}, que no está en el corpus cargado para esa "
                "fecha: lo recuperado no puede responder sobre él."
            )
    return faltan


def requiere_revision(redaccion: Redaccion, missing_information: Sequence[str]) -> bool:
    """Punto 6 del ADR. Por omisión `True`: pasar a `False` exige todo lo contrario."""
    return not (
        redaccion.redactada
        and not redaccion.sin_evidencia
        and redaccion.modelo_no_disponible is None
        and redaccion.confidence == Decimal("1.00")
        and not missing_information
    )
