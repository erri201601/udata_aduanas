"""Puertos del RGI Engine: lo que el motor necesita del exterior.

El motor no consulta la base ni llama a ningún proveedor de IA. Declara qué
necesita y alguien se lo inyecta. Eso permite tres cosas:

1. Que el motor se pueda construir y probar HOY, sin esperar a que existan la
   tarifa cargada (Persona 2) ni el Product DNA real (Persona 3).
2. Que `core/` no importe la capa de persistencia (§29 del maestro).
3. Que los tests corran con catálogos deterministas en vez de contra una base,
   que es lo que permite tener casos de clasificación reproducibles.

Y de paso fija el contrato al revés: al declarar qué necesita el RGI de un
catálogo arancelario, Persona 2 sabe qué forma deben tener sus datos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from core.rgi_engine.context import ClassificationContext, TariffCandidate


@runtime_checkable
class TariffCatalog(Protocol):
    """Acceso a la nomenclatura vigente en una fecha.

    Toda consulta lleva `on_date` y no es opcional: clasificar una operación
    de 2024 con la tarifa de 2026 produce un resultado equivocado con
    apariencia de correcto (§14 del maestro). Hacer el parámetro obligatorio
    convierte esa regla en algo que no se puede olvidar.
    """

    def headings(
        self,
        *,
        on_date: date,
        terms: Sequence[str],
        cobertura_minima: int | None = None,
    ) -> Sequence[TariffCandidate]:
        """Partidas (4 dígitos) cuyo texto coincide con los términos dados.

        Por defecto sólo las que cubren MÁS términos, que es lo que evita que
        el ruido gane por la RGI 3 c). `cobertura_minima` pide un conjunto más
        amplio —las que cubren al menos esa cantidad— para que quien llama
        pueda recuperar una partida que el recorte se llevó por delante.

        Quien la use tiene que tener una razón sustantiva para recuperarla, no
        sólo que exista: el motor sólo readmite las que CUMPLEN una condición
        medible de su propio texto.
        """
        ...

    def subheadings(self, *, on_date: date, heading: str) -> Sequence[TariffCandidate]:
        """Subpartidas (6 dígitos) que dependen de una partida."""
        ...

    def fractions(self, *, on_date: date, subheading: str) -> Sequence[TariffCandidate]:
        """Fracciones mexicanas (8 dígitos) que dependen de una subpartida."""
        ...


@runtime_checkable
class LegalNotes(Protocol):
    """Notas legales de sección y capítulo.

    La RGI 1 dice que la clasificación se determina por los textos de las
    partidas Y por las notas de sección o capítulo. Sin acceso a las notas, la
    RGI 1 está a medias y el motor no debe fingir que la aplicó.
    """

    def notes_for(self, *, on_date: date, chapter: str) -> Sequence[str]:
        """Notas aplicables a un capítulo, incluidas las de su sección."""
        ...

    def excludes(self, *, on_date: date, heading: str, terms: Sequence[str]) -> str | None:
        """Devuelve la nota que EXCLUYE la mercancía de la partida, si existe.

        Las notas de exclusión resuelven más clasificaciones que cualquier otra
        cosa: "este capítulo no comprende...". Devuelve el texto de la nota, o
        `None` si nada excluye.
        """
        ...


@runtime_checkable
class Interpreter(Protocol):
    """Ayuda interpretativa de un modelo de lenguaje.

    Es OPCIONAL: el motor funciona sin él, con menos alcance. Cuando está, el
    modelo sugiere e interpreta, pero NUNCA decide el estado ni fija el código:
    eso lo hace la máquina, y por eso `suggest_terms` devuelve términos de
    búsqueda y no una fracción.

    §18 del maestro: "el LLM puede ayudar a interpretar; el estado y las reglas
    deben ser trazables".
    """

    def suggest_terms(self, *, context: ClassificationContext) -> Sequence[str]:
        """Términos de nomenclatura para buscar en el catálogo.

        Traduce el lenguaje comercial del producto al de la tarifa: de
        "laptop gamer 16 pulgadas" a "máquina automática tratamiento de datos".
        """
        ...

    def essential_character(
        self, *, context: ClassificationContext, candidates: Sequence[TariffCandidate]
    ) -> tuple[str, str] | None:
        """Para la RGI 3 b): qué candidato confiere el carácter esencial.

        Devuelve `(código, razonamiento)`, o `None` si no puede determinarlo —
        que es una respuesta legítima y lleva a revisión humana, no a elegir
        al azar.
        """
        ...
