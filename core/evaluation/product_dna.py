"""Evaluación del Product DNA (§39): las cuatro medidas, contra fichas con respuesta conocida.

    field extraction accuracy       ¿lo que la ficha dice, se extrajo bien?
    hallucinated attribute rate     ¿se afirmó algo que la ficha no dice?
    evidence coverage               ¿cada dato afirmado dice dónde está?
    missing information detection   ¿lo que la ficha no dice, salió MISSING?

QUÉ ES UNA FICHA CON RESPUESTA CONOCIDA

Un texto y, por separado, lo que dice (`esperado`) y lo que NO dice
(`ausentes`), en los nombres del catálogo del §16. Los atributos que no están
en ninguna de las dos listas no se puntúan: hay datos —la función, el uso— que
una ficha puede insinuar sin decir, y puntuarlos sería ajustar la medida a una
opinión.

QUÉ CUENTA COMO ALUCINACIÓN

Afirmar un valor —cualquier estado que no sea MISSING— para un atributo que la
ficha NO contiene. Un valor equivocado de un atributo que sí contiene es un
error de extracción, no una alucinación: se cuenta en la primera medida. Las
alucinaciones que el modelo declaró como INFERRED se cuentan aparte, porque al
menos no se presentaron como hechos.

Puro: no sabe de modelos ni de base. Lo alimenta `apps/evaluacion/product_dna_39.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from core.evaluation.intervalos import wilson

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from core.product_dna.types import ProductDnaDraft


@dataclass(frozen=True)
class FichaDeReferencia:
    """Un documento y su respuesta conocida, en nombres del §16."""

    id: str
    texto: str
    esperado: Mapping[str, str]
    """Lo que la ficha DICE: atributo → valor."""
    ausentes: tuple[str, ...]
    """Lo que la ficha NO dice. Tiene que salir MISSING."""
    data_origin: str = "SYNTHETIC"


def _palabras(texto: str) -> set[str]:
    sin_acentos = unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore").decode()
    return {p.strip(".") for p in re.findall(r"[a-z0-9.]+", sin_acentos) if p.strip(".")}


def coincide(esperado: str, obtenido: str | None) -> bool:
    """¿El valor extraído dice lo mismo que el esperado?

    Todas las palabras esperadas tienen que estar en lo extraído, enteras y sin
    acentos ni mayúsculas: «acero galvanizado» y «Acero galvanizado, 6x36»
    coinciden; «acero» a secas NO, porque se quedó a medias. Por palabras y no
    por subcadena porque «10» estaría dentro de «100 mm». La unidad la añade el
    motor («10 mm»), así que basta con que el número esperado esté.
    """
    if not obtenido:
        return False
    a, b = _palabras(esperado), _palabras(obtenido)
    return bool(a) and a <= b


@dataclass(frozen=True)
class ResultadoFicha:
    """Las cuentas de una ficha. Se suman en `Reporte`."""

    id: str
    esperados: int = 0
    aciertos: int = 0
    afirmados: int = 0
    alucinados: int = 0
    alucinados_como_inferencia: int = 0
    con_localizador: int = 0
    ausentes: int = 0
    ausencias_detectadas: int = 0
    fallos: tuple[str, ...] = ()
    """Qué salió mal, legible: «materials: esperado 'acero', obtenido 'aluminio'»."""


def comparar(ficha: FichaDeReferencia, borrador: ProductDnaDraft) -> ResultadoFicha:
    """Compara lo extraído con la respuesta conocida."""
    por_nombre = {a.name: a for a in borrador.attributes}
    fallos: list[str] = []

    aciertos = 0
    for nombre, valor in ficha.esperado.items():
        atributo = por_nombre.get(nombre)
        obtenido = atributo.value if atributo and atributo.is_known else None
        if coincide(valor, obtenido):
            aciertos += 1
        else:
            fallos.append(f"{nombre}: esperado {valor!r}, obtenido {obtenido!r}")

    conocidos = [a for a in borrador.attributes if a.is_known]
    alucinados = [a for a in conocidos if a.name in ficha.ausentes]
    fallos += [
        f"{a.name}: la ficha no lo dice y salió {a.value!r} ({a.status})" for a in alucinados
    ]

    detectadas = sum(
        1
        for nombre in ficha.ausentes
        if not (por_nombre.get(nombre) and por_nombre[nombre].is_known)
    )

    return ResultadoFicha(
        id=ficha.id,
        esperados=len(ficha.esperado),
        aciertos=aciertos,
        afirmados=len(conocidos),
        alucinados=len(alucinados),
        alucinados_como_inferencia=sum(1 for a in alucinados if a.status == "INFERRED"),
        con_localizador=sum(1 for a in conocidos if a.locator),
        ausentes=len(ficha.ausentes),
        ausencias_detectadas=detectadas,
        fallos=tuple(fallos),
    )


@dataclass(frozen=True)
class Medida:
    """Una proporción con su n y su margen al 95 % (Wilson)."""

    nombre: str
    exitos: int
    total: int

    @property
    def porcentaje(self) -> Decimal | None:
        if self.total == 0:
            return None
        return (Decimal(self.exitos) * 100 / Decimal(self.total)).quantize(Decimal("0.01"))

    @property
    def margen(self) -> Decimal | None:
        return wilson(self.exitos, self.total)

    def linea(self) -> str:
        if self.porcentaje is None:
            return f"{self.nombre:<34} sin casos (n = 0): desconocido, no cero"
        return (
            f"{self.nombre:<34} {self.porcentaje:>6} %  "
            f"({self.exitos} de {self.total}) · ±{self.margen} puntos al 95 %"
        )


@dataclass(frozen=True)
class Reporte:
    """Las cuatro medidas del §39 para Product DNA, sumadas sobre todas las fichas."""

    fichas: tuple[ResultadoFicha, ...] = field(default_factory=tuple)

    def _suma(self, campo: str) -> int:
        return sum(getattr(f, campo) for f in self.fichas)

    @property
    def precision_por_campo(self) -> Medida:
        return Medida("field extraction accuracy", self._suma("aciertos"), self._suma("esperados"))

    @property
    def alucinacion(self) -> Medida:
        """Más bajo es mejor."""
        return Medida(
            "hallucinated attribute rate", self._suma("alucinados"), self._suma("afirmados")
        )

    @property
    def cobertura_de_evidencia(self) -> Medida:
        return Medida("evidence coverage", self._suma("con_localizador"), self._suma("afirmados"))

    @property
    def deteccion_de_faltantes(self) -> Medida:
        return Medida(
            "missing information detection",
            self._suma("ausencias_detectadas"),
            self._suma("ausentes"),
        )

    def medidas(self) -> Sequence[Medida]:
        return (
            self.precision_por_campo,
            self.alucinacion,
            self.cobertura_de_evidencia,
            self.deteccion_de_faltantes,
        )
