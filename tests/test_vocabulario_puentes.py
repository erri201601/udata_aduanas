"""Los puentes de vocabulario: de una palabra de la ficha a una de la tarifa.

LA TABLA EXISTÍA Y NO PODÍA CAMBIAR NI UNA CLASIFICACIÓN

Dos defectos independientes la dejaban inerte, y cada uno bastaba por sí solo:

    1. el emparejamiento era por igualdad exacta contra una PALABRA de la
       ficha, así que un término de dos palabras no casaba nunca
    2. los puentes se añaden detrás de la ficha entera y luego se corta a
       `MAX_TERMINOS`, y todas las fichas del corpus tienen seis palabras o
       más: el puente cae siempre fuera del corte

No se había notado porque las nueve filas cargadas eran de una sola palabra y
porque nadie había medido si el puente llegaba a la consulta. La primera vez
que un clasificador contestó mirando dos palabras —César, 5-oct— su respuesta
quedó firmada, guardada y sin efecto.

AQUÍ SE ARREGLA EL PRIMERO. EL SEGUNDO SE MIDIÓ Y SE DEJÓ COMO ESTABA

Dejar pasar los puentes bajó la precisión de 100 % a 71.67 % sobre el corpus:
el puente también le da un punto de cobertura a la posición de cuyo texto
salió, y con eso le hace ganar el recorte. Catorce vajillas que estaban bien
pasaron a la 6911 —«de porcelana»— por el puente «vajilla» → «mesa». El
razonamiento completo y los números están en `_busqueda`.

Así que del tope se prueba aquí su invariante: la ficha nunca pierde un sitio
por un puente.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from apps.api.clasificacion import _busqueda, _con_sinonimos
from apps.api.dna import MAX_TERMINOS
from core.product_dna import ExtractedAttribute, ProductDnaDraft

pytestmark = pytest.mark.unit

FECHA = date(2026, 3, 15)

#: Palabras distintas, largas y SIN dígitos. `_palabras` descarta los dígitos,
#: así que «palabra0 … palabra5» se colapsaba en una sola palabra: la ficha de
#: prueba no llegaba al tope y el test medía otra cosa.
BANCO = ("acero", "cobre", "plomo", "niquel", "bronce", "hierro", "titanio", "platino")


class SesionFalsa:
    """Devuelve las filas de vocabulario que se le den, filtrando por `kind`.

    Filtra de verdad y no devuelve todo: lo que este fichero prueba es
    precisamente que una fila `EXCLUYE` no se use como puente, y una sesión que
    ignorara el `WHERE` haría pasar ese test por el camino equivocado.
    """

    def __init__(self, filas: list[tuple[str, str, str]]) -> None:
        self._filas = filas

    def execute(self, sentencia: Any) -> Any:
        # Con `str(sentencia)` el valor sale como parámetro ligado (`:kind_1`)
        # y el filtro era invisible: la sesión devolvía las filas `EXCLUYE`
        # para la consulta de `EQUIVALE` y los tests fallaban todos a la vez
        # por un motivo que no tenía nada que ver con lo que prueban.
        sql = str(sentencia.compile(compile_kwargs={"literal_binds": True}))
        kind = "EQUIVALE" if "EQUIVALE" in sql else "EXCLUYE"
        r = type("R", (), {})()
        r.all = lambda: [(c, n) for c, n, k in self._filas if k == kind]
        return r


def _ficha(*palabras: str) -> ProductDnaDraft:
    return ProductDnaDraft(
        attributes=tuple(
            ExtractedAttribute(name=f"a{i}", value=p, status="OBSERVED", locator="p.1")
            for i, p in enumerate(palabras)
        ),
        summary="",
    )


# ── Un término de dos palabras tiene que poder casar ────────────────────────


def test_un_termino_de_dos_palabras_casa_por_sus_palabras() -> None:
    """«acero inoxidable» no es una palabra, y con igualdad exacta no casaba.

    Es la mitad de las respuestas de César del 5-oct: contestó mirando «acero
    inoxidable», «sin recubrimiento», «acero al carbono», «domestico/cocina».
    Ninguna podía disparar un puente.
    """
    s = SesionFalsa([("acero inoxidable", "De hierro o acero", "EQUIVALE")])

    salida = _con_sinonimos(s, ["ESTROPAJO", "ACERO", "INOXIDABLE"], on_date=FECHA)

    assert "De hierro o acero" in salida


def test_hacen_falta_todas_las_palabras_no_una() -> None:
    """Con una basta, «acero» arrastraría el puente de «acero inoxidable» a
    cualquier cosa de acero: a un cable, a un tornillo, a una tubería."""
    s = SesionFalsa([("acero inoxidable", "De hierro o acero", "EQUIVALE")])

    salida = _con_sinonimos(s, ["CABLE", "ACERO", "GALVANIZADO"], on_date=FECHA)

    assert "De hierro o acero" not in salida


def test_una_sola_palabra_sigue_comportandose_igual() -> None:
    """Las nueve filas que ya había son de una palabra: no deben cambiar."""
    s = SesionFalsa([("limpieza", "esponjas", "EQUIVALE")])

    assert "esponjas" in _con_sinonimos(s, ["ESTROPAJO", "LIMPIEZA"], on_date=FECHA)
    assert "esponjas" not in _con_sinonimos(s, ["ESTROPAJO", "COCINA"], on_date=FECHA)


def test_un_termino_sin_palabras_distintivas_no_hace_puente() -> None:
    """`«6x19»` es una notación, no una palabra: no ensancha una búsqueda de
    texto. Es el límite de esta vía, y es deliberado — para DESCARTAR sí vale,
    porque la exclusión compara contra el texto entero de la ficha."""
    s = SesionFalsa([("6x19", "constituidos por 7 alambres", "EQUIVALE")])

    salida = _con_sinonimos(s, ["CABLE", "ACERO", "CONSTRUCCION"], on_date=FECHA)

    assert "constituidos por 7 alambres" not in salida


# ── Una exclusión no es un puente ───────────────────────────────────────────


def test_una_exclusion_no_se_usa_para_buscar() -> None:
    """La consulta no filtraba por `kind`.

    `«ceramica vidriada» → «talavera»` es un NO firmado: la ficha no es
    Talavera. Meterlo como término de búsqueda empujaría al motor justo a la
    posición que el clasificador descartó.

    No llegó a pasar porque con la igualdad exacta de antes ninguna fila
    `EXCLUYE` de dos palabras podía casar. Al arreglar el emparejamiento, sí
    habría pasado.
    """
    s = SesionFalsa([("ceramica vidriada", "talavera", "EXCLUYE")])

    salida = _con_sinonimos(s, ["VAJILLA", "CERAMICA", "VIDRIADA"], on_date=FECHA)

    assert "talavera" not in salida


# ── El tope ya no se los lleva por delante ──────────────────────────────────


def test_un_puente_no_le_quita_el_sitio_a_ninguna_palabra_de_la_ficha() -> None:
    """El invariante del tope, y es el que importa.

    Quitar una palabra de la ficha para meter un puente es el experimento que
    ya salió mal: «SOLDADA» fuera del tope y la tubería soldada resolviendo a
    tubos SIN soldadura. Las palabras de la ficha entran primero y el puente
    sólo ocupa lo que sobre.

    Consecuencia medida: con una ficha de seis palabras o más —todas las del
    corpus— el puente no llega a la consulta. Se dejó así a propósito, porque
    dejarlo pasar costó 14 aciertos; el motivo completo está en `_busqueda`.
    """
    assert len(BANCO) > MAX_TERMINOS, "la ficha tiene que pasarse del tope"
    ficha = _ficha(*BANCO, "limpieza")
    s = SesionFalsa([("limpieza", "esponjas", "EQUIVALE")])

    salida = _busqueda(s, ficha, FECHA)

    assert salida == list(BANCO[:MAX_TERMINOS])


def test_con_sitio_de_sobra_el_puente_si_entra() -> None:
    """Que no quepa no es que no exista: con una ficha corta, el puente entra.

    Sin este test, `_con_sinonimos` entero podría dejar de funcionar sin que
    nada fallara, y el día que la cobertura sepa distinguir un puente de una
    palabra de la ficha nadie sabría que esta mitad ya estaba lista.
    """
    ficha = _ficha("limpieza", "cobre")
    s = SesionFalsa([("limpieza", "esponjas", "EQUIVALE")])

    assert "esponjas" in _busqueda(s, ficha, FECHA)
