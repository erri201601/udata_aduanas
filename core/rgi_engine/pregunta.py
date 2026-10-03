"""La pregunta exacta que le falta al motor para desempatar.

EL PROBLEMA QUE RESUELVE

Cuando el motor se atasca dice «desempate de subpartida por un clasificador».
Es honesto y es inútil: obliga a la persona a reconstruir desde cero todo el
razonamiento que la máquina ya hizo, y su respuesta resuelve UN caso.

Medido sobre el corpus el 2-oct: 52 decisiones atascadas, concentradas en ocho
familias —8528 con 12, 7305 con 11, 7312 con 8—. La misma duda, una y otra vez.

LO QUE CAMBIA

El motor sabe qué AFIRMA la ficha y qué EXIGE cada candidata. Con eso puede
formular una pregunta de sí o no:

    La ficha dice  proceso_soldadura = «HFW longitudinal»
    La 730511 exige                    «arco sumergido»
    ¿Son lo mismo?

Eso se contesta en cinco segundos, se guarda firmado, y no se vuelve a
preguntar. Un minuto de un clasificador deja de resolver un caso y pasa a
resolver una familia entera.

LO QUE NO HACE

No elige. No propone una respuesta ni la insinúa. Sólo pone delante los dos
textos que no supo reconciliar — porque el puente entre «HFW» y «arco
sumergido» no está en ninguno de los dos documentos, y ningún algoritmo que
lea ambos puede inventarlo.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from core.rgi_engine.context import ClassificationContext, TariffCandidate

#: Más de esto y no es una pregunta: es pedirle a alguien que clasifique.
MAX_CANDIDATAS_PREGUNTABLES: Final[int] = 4

#: Por debajo de esta longitud una palabra no distingue nada.
_MINIMO: Final[int] = 5


class Pregunta(BaseModel):
    """Lo que el motor necesita saber, en forma de sí o no."""

    model_config = ConfigDict(frozen=True)

    atributo: str
    """Qué atributo de la ficha está en juego: `proceso_soldadura`."""

    valor_declarado: str
    """Lo que la ficha afirma: «HFW longitudinal»."""

    codigo: str
    """La posición que no se pudo descartar: `730511`."""

    exige: str
    """Lo que esa posición exige y la ficha no dice con esas palabras."""

    texto: str
    """La pregunta, escrita para una persona."""


def _plano(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore").decode()


def _palabras(texto: str) -> set[str]:
    return {p for p in re.findall(r"[^\W\d_]+", _plano(texto)) if len(p) >= _MINIMO}


def _raices(texto: str) -> set[str]:
    """Las palabras recortadas a su raíz, para que el plural no despiste.

    «cable» y «cables» son la misma palabra, y una pregunta que no lo viera
    preguntaría por algo que la ficha ya dice. Se usa SÓLO para callar
    preguntas, nunca para decidir: un recorte de más hace que preguntemos
    menos, que es el lado seguro del error.
    """
    return {p[:_MINIMO] for p in _palabras(texto)}


def formular(context: ClassificationContext, candidatas: list[TariffCandidate]) -> list[Pregunta]:
    """Las preguntas que desatascarían este caso, o lista vacía.

    Se pregunta sólo por lo que la ficha AFIRMA y la candidata EXIGE sin que
    compartan vocabulario. Si comparten palabras, el motor ya tenía con qué y
    no atascarse era su trabajo; si la ficha no afirma nada de eso, no hay
    pregunta que hacer — falta el dato, que es otra cosa y ya se reporta.

    Con muchas candidatas no se pregunta nada: cuatro preguntas de sí o no no
    son una pregunta, son el trabajo entero. Ahí la respuesta honesta sigue
    siendo mandarlo a un clasificador.
    """
    if not candidatas or len(candidatas) > MAX_CANDIDATAS_PREGUNTABLES:
        return []

    hechos = [h for h in context.facts if h.is_solid and h.value]
    if not hechos:
        return []

    # Todo lo que la ficha dice de la mercancía, incluida su descripción.
    todo_lo_que_consta = _raices(" ".join([context.description, *(h.value or "" for h in hechos)]))

    preguntas: list[Pregunta] = []
    for candidata in candidatas:
        distintivas = _palabras(candidata.text)
        if not distintivas:
            continue

        # SI ALGO DE LA FICHA YA TOCA ESTA POSICIÓN, NO SE PREGUNTA POR ELLA.
        #
        # La comprobación es por CANDIDATA y no por hecho, y esa diferencia
        # importa: antes se saltaba el hecho que coincidía y preguntaba con el
        # siguiente, produciendo «la ficha dice material = acero, la 731210
        # exige "Cables", ¿son lo mismo?». Un material contra un tipo de
        # producto. La descripción ya decía CABLE DE ACERO — el motor tenía con
        # qué, y la pregunta sólo gastaba el tiempo de quien la leyera.
        if _raices(candidata.text) & todo_lo_que_consta:
            continue

        for hecho in hechos:
            afirmadas = _palabras(hecho.value or "")
            if not afirmadas:
                continue
            exige = _lo_que_exige(candidata.text)
            if not exige or _es_residual(exige):
                # Un residual se lleva lo que sobre; no hay nada que preguntar
                # sobre él. Si al descartar las específicas queda sólo él, ya
                # se resuelve sin preguntar nada.
                continue
            preguntas.append(
                Pregunta(
                    atributo=hecho.name,
                    valor_declarado=hecho.value or "",
                    codigo=candidata.code,
                    exige=exige,
                    texto=(
                        f"La ficha dice {hecho.name} = «{hecho.value}». "
                        f"La posición {candidata.code} exige «{exige}». "
                        f"¿Son lo mismo?"
                    ),
                )
            )
            break  # una pregunta por candidata: más es ruido
    return preguntas


#: Una posición residual no EXIGE nada: recoge lo que no cayó en sus hermanas.
#: Preguntar «¿es cerámica vidriada lo mismo que "Los demás"?» no tiene
#: respuesta, y una pregunta sin respuesta posible gasta el tiempo de la única
#: persona cuyo tiempo no se puede gastar.
_RESIDUALES: Final[tuple[str, ...]] = (
    "los demas",
    "las demas",
    "los demas,",
    "las demas,",
    "otros",
    "otras",
)


def _es_residual(texto: str) -> bool:
    """¿Es una posición de recogida y no una exigencia?"""
    plano = _plano(texto).strip(" .:")
    return any(plano == r or plano.startswith(r + " ") for r in _RESIDUALES)


def _lo_que_exige(texto: str) -> str:
    """El trozo del texto legal sobre el que se pregunta.

    El texto entero de una posición no es una pregunta —«Los demás, soldados
    longitudinalmente» incluye su encabezado de grupo y su residual—, así que
    se recorta a la primera frase, que es donde la nomenclatura pone el
    calificativo que distingue.
    """
    limpio = texto.split(". ")[-1].strip(" .")
    return limpio[:120]
