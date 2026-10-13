"""Evaluación de la búsqueda jurídica (§39) sobre el contrato del Copilot (ADR 0010).

    retrieval hit rate       ¿entre lo recuperado está el artículo que responde?
    source precision         ¿lo que `answer` cita es lo que responde?
    unsupported answer rate  ¿se entregó una respuesta sin sustento?

LAS RESPUESTAS LAS ETIQUETAN PERSONAS

Qué artículo responde una pregunta es una afirmación jurídica. Escribirla de
memoria sería inventar fundamento (regla 1). Por eso cada pregunta lleva
`validado_por`: sin nombre, la pregunta no entra en ninguna medida y el reporte
dice cuántas esperan etiqueta.

UNA RESPUESTA SIN SUSTENTO ES CUALQUIERA DE ESTAS DOS

- Se entregó una redacción con alguna oración sin cita (`confidence < 1`, que
  es la misma definición del ADR 0010, punto 4).
- La pregunta no tiene respuesta en el corpus (`sin_corpus`) y aun así se
  entregó una redacción sin declarar nada en `missing_information`.

Puro: recibe la respuesta ya obtenida. La pide `apps/evaluacion/busqueda_juridica_39.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.evaluation.product_dna import Medida

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class PreguntaEtiquetada:
    """Una pregunta, su fecha y qué la responde, según quien la firmó."""

    id: str
    pregunta: str
    fecha: date
    esperado: tuple[tuple[str, str], ...] = ()
    """(documento, artículo) que responden. Vacío con `sin_corpus`."""
    sin_corpus: bool = False
    """La base cargada NO tiene con qué responder: lo correcto es decirlo."""
    validado_por: str | None = None
    nota: str | None = None

    @property
    def etiquetada(self) -> bool:
        return bool(self.validado_por) and (bool(self.esperado) or self.sin_corpus)

    @classmethod
    def desde(cls, crudo: Mapping[str, Any]) -> PreguntaEtiquetada:
        return cls(
            id=str(crudo["id"]),
            pregunta=str(crudo["pregunta"]),
            fecha=date.fromisoformat(str(crudo["fecha"])),
            esperado=tuple(
                (str(e["documento"]), str(e["articulo"])) for e in crudo.get("esperado") or []
            ),
            sin_corpus=bool(crudo.get("sin_corpus", False)),
            validado_por=crudo.get("validado_por") or None,
            nota=crudo.get("nota"),
        )


def _plano(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9-]+", sin_acentos))


def _articulo(texto: str | None) -> str:
    """«Artículo 36-A», «art. 36-A» y «36-A» son el mismo."""
    plano = _plano(texto or "")
    return re.sub(r"^(articulo|art)\s+", "", plano)


def es_el_esperado(pasaje: Mapping[str, Any], esperado: tuple[str, str]) -> bool:
    documento, articulo = esperado
    return _plano(documento) in _plano(str(pasaje.get("documento") or "")) and _articulo(
        str(pasaje.get("articulo") or "")
    ) == _articulo(articulo)


@dataclass(frozen=True)
class ResultadoPregunta:
    id: str
    recupero: bool | None
    """`None` con `sin_corpus`: no hay artículo que recuperar."""
    citadas: int = 0
    citadas_pertinentes: int = 0
    entregada: bool = False
    sin_sustento: bool = False


def evaluar(pregunta: PreguntaEtiquetada, respuesta: Mapping[str, Any]) -> ResultadoPregunta:
    """Compara una respuesta del Copilot con la etiqueta de la pregunta."""
    evidencia = respuesta.get("evidence") or respuesta.get("pasajes") or []
    fuentes = respuesta.get("sources") or []
    entregada = bool(respuesta.get("redacta_respuesta"))
    confianza = Decimal(str(respuesta.get("confidence", "0")))
    faltan = respuesta.get("missing_information") or []

    recupero = (
        None
        if pregunta.sin_corpus
        else any(es_el_esperado(p, e) for p in evidencia for e in pregunta.esperado)
    )
    pertinentes = (
        0
        if pregunta.sin_corpus
        else sum(1 for f in fuentes if any(es_el_esperado(f, e) for e in pregunta.esperado))
    )
    sin_sustento = entregada and (confianza < Decimal("1") or (pregunta.sin_corpus and not faltan))
    return ResultadoPregunta(
        id=pregunta.id,
        recupero=recupero,
        citadas=len(fuentes),
        citadas_pertinentes=pertinentes,
        entregada=entregada,
        sin_sustento=sin_sustento,
    )


@dataclass(frozen=True)
class Reporte:
    preguntas: tuple[ResultadoPregunta, ...] = field(default_factory=tuple)
    sin_etiquetar: int = 0

    @property
    def acierto_de_recuperacion(self) -> Medida:
        medibles = [p for p in self.preguntas if p.recupero is not None]
        return Medida("retrieval hit rate", sum(1 for p in medibles if p.recupero), len(medibles))

    @property
    def precision_de_fuentes(self) -> Medida:
        return Medida(
            "source precision",
            sum(p.citadas_pertinentes for p in self.preguntas),
            sum(p.citadas for p in self.preguntas),
        )

    @property
    def respuestas_sin_sustento(self) -> Medida:
        """Más bajo es mejor."""
        entregadas = [p for p in self.preguntas if p.entregada]
        return Medida(
            "unsupported answer rate", sum(1 for p in entregadas if p.sin_sustento), len(entregadas)
        )

    def medidas(self) -> Sequence[Medida]:
        return (
            self.acierto_de_recuperacion,
            self.precision_de_fuentes,
            self.respuestas_sin_sustento,
        )
