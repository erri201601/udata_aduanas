"""Métrica de detección del §26: TP, FP, FN, TN, precision, recall y F1.

QUÉ MIDE, Y CONTRA QUÉ

Un corpus con anomalías sembradas dice qué está mal en cada partida. El motor
dice qué encontró. Esto compara las dos listas. Nada más — y por eso es puro:
no conoce la base, recibe los eventos y los hallazgos ya leídos.

EL EMPAREJAMIENTO VA POR TIPO, NO POR NOMBRE DE CAMPO

Un evento y un hallazgo se emparejan si caen en la MISMA partida y el tipo de
error se corresponde con el tipo de hallazgo. No por `expected_field`: el
ground truth sembrado escribe `tariff_fraction` y el motor emite
`fraction_code` para lo mismo. Dos vocabularios cerrados se pueden mapear una
vez; dos cadenas libres se desincronizan en silencio y la métrica saldría en
cero sin que nada falle.

EL DENOMINADOR SALE DEL DATO, NO DE UNA NOTA AL PIE

`expected_detection = false` marca los eventos que NADIE puede detectar con lo
que trae el documento —las anomalías de cantidad, comprobadas por Persona 1—.
Se excluyen del recall y se reportan aparte. Que la exclusión venga de la base
y no de un filtro escrito aquí es lo que impide que alguien la olvide.

UN FALSO NEGATIVO NO DICE POR QUÉ, Y HAY TRES PORQUÉS DISTINTOS

Los tres se ven iguales en la tabla y no son lo mismo (Persona 1, 22-sep):

  · EL DETECTOR NO EXISTE — nadie lo ha construido. La unidad y las tres
    comprobaciones fiscales están aquí: no hay `UNIT_MISMATCH` ni ninguna
    divergencia de tasa en el vocabulario del §18.
  · EL DETECTOR EXISTE Y NO PUDO — la fracción: el motor no logra determinar
    cuál era la correcta, y sin eso no puede afirmar que la declarada esté
    mal. Es una limitación honesta, no un fallo de detección.
  · EL DETECTOR EXISTE Y NO CAZÓ — eso sí es fallo del motor.

Sin separarlos, un recall bajo parece que el motor falla cuando la mitad del
hueco es código que no hemos escrito.

TRES LÍMITES QUE EL REPORTE DECLARA, PORQUE SIN ELLOS EL NÚMERO ENGAÑA

1. Los eventos sin detector posible no entran al recall, y se dice cuántos son.
2. El NICO se parte en dos: lo que el catálogo caza solo —un NICO que no
   existe en su fracción— y lo que exige ficha técnica. Son capacidades
   distintas y juntarlas da una cifra que no significa nada.
3. Con seis casos por tipo, el intervalo de confianza es enorme. Se calcula y
   se enseña: sirve para ver si un tipo falla del todo, no para afirmar un
   porcentaje.

LOS FALSOS POSITIVOS IMPORTAN TANTO COMO LOS ACIERTOS

Un sistema que grita en todas las partidas detecta todo y no sirve. Por eso se
cuentan sobre las partidas declaradas limpias, y los de origen se reportan
aparte: son una revisión humana pedida, no una acusación, y quien lee tiene
que poder separarlos del ruido duro.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

#: Qué hallazgo del motor corresponde a cada tipo de error sembrado. Los dos
#: son vocabularios cerrados —`ERROR_TYPE` y `DivergenceType`— así que el
#: mapeo se escribe una vez y se comprueba con un test.
DETECTOR_POR_ERROR: Final[Mapping[str, str]] = {
    "WRONG_FRACTION": "FRACTION_MISMATCH",
    "WRONG_NICO": "NICO_MISMATCH",
    "WRONG_ORIGIN": "ORIGIN_MISMATCH",
    "WRONG_VALUE": "VALUE_MISMATCH",
    "MISSING_NOM": "MISSING_NOM",
    "WRONG_IDENTIFIER": "IDENTIFIER_MISMATCH",
    "WRONG_UNIT": "UNIT_MISMATCH",
    "MISSING_TECHNICAL_FIELD": "MISSING_TECHNICAL_FIELD",
    "INCONSISTENT_SKU_CLASSIFICATION": "INCONSISTENT_SKU_CLASSIFICATION",
}

#: Tipos sembrados para los que el motor NO tiene detector hoy. No es lo mismo
#: que fallar: es no haberlo construido, y el reporte lo dice con ese nombre.
SIN_DETECTOR: Final[frozenset[str]] = frozenset(
    {
        "INCONSISTENT_QUANTITY",
        "MISSED_PROSEC",
        "MISSED_PREFERENCE",
        "MISSING_INCREMENTABLE",
    }
)

#: El hallazgo de origen pide revisión humana, no acusa. Se cuenta como falso
#: positivo igual —para quien revisa es ruido— pero se reporta aparte.
HALLAZGO_DE_REVISION: Final = "ORIGIN_MISMATCH"

#: Subtipos del NICO. No se deciden a mano: los calcula quien lee el catálogo.
NICO_LO_CAZA_EL_CATALOGO: Final = "WRONG_NICO/catálogo"
NICO_EXIGE_FICHA: Final = "WRONG_NICO/ficha técnica"

#: El corpus colapsa cuatro anomalías distintas en WRONG_VALUE y las separa por
#: `expected_field`. Sólo una tiene detector: la del valor en aduana, que se
#: comprueba con la aritmética de la partida. Las otras tres son fiscales y
#: nadie las ha construido — no hay divergencia de tasa en el §18.
SUBTIPO_POR_CAMPO: Final[Mapping[str, str]] = {
    "customs_value": "WRONG_VALUE/valor en aduana",
    "igi_rate": "WRONG_VALUE/tasa de IGI",
    "iva_base": "WRONG_VALUE/base de IVA",
    "iva_amount": "WRONG_VALUE/importe de IVA",
}

#: Qué hallazgo corresponde a cada subtipo, cuando el del tipo no alcanza. Los
#: cuatro sabores de WRONG_VALUE los caza gente distinta: el valor en aduana lo
#: delata la aritmética de la partida, la tasa de IGI la tarifa, y la base y el
#: importe de IVA salen los dos desviados del mismo cálculo — desde el pedimento
#: no se distingue cuál se alteró, y el motor no lo afirma.
DETECTOR_POR_SUBTIPO: Final[Mapping[str, str]] = {
    "WRONG_VALUE/valor en aduana": "VALUE_MISMATCH",
    "WRONG_VALUE/tasa de IGI": "IGI_RATE_MISMATCH",
    "WRONG_VALUE/base de IVA": "VAT_MISMATCH",
    "WRONG_VALUE/importe de IVA": "VAT_MISMATCH",
}

#: Subtipos sin detector construido. Se cuentan aparte de los que sí lo tienen.
SUBTIPOS_SIN_DETECTOR: Final[frozenset[str]] = frozenset({NICO_EXIGE_FICHA})

#: Por qué no se detectó. Tres cosas distintas que se ven iguales en un FN.
SIN_DETECTOR_CONSTRUIDO: Final = "el detector no existe"
NO_PUDO_DETERMINARLO: Final = "el detector existe y no pudo"
NO_LO_CAZO: Final = "el detector existe y no cazó"

_Z: Final = 1.96  # 95 %
_CIEN: Final = Decimal(100)
_DOS: Final = Decimal("0.01")


@dataclass(frozen=True)
class Evento:
    """Una anomalía sembrada, tal como la trae el ground truth."""

    partida_id: str
    error_type: str
    detectable: bool
    """`expected_detection`. `False` = nadie puede detectarlo con el documento."""
    subtipo: str | None = None
    """Lo calcula quien tiene el catálogo o el `expected_field` delante.

    Para el NICO y para los cuatro sabores de WRONG_VALUE: son capacidades
    distintas y mezclarlas da una cifra que no significa nada.
    """

    pudo_intentarlo: bool = True
    """`False` cuando el motor no llegó a tener contra qué comparar.

    Hoy pasa con la fracción: si la clasificación no se sostuvo, el motor no
    puede afirmar que la declarada esté mal. Eso es una limitación dicha, no
    un fallo de detección, y el reporte las separa.
    """

    @property
    def etiqueta(self) -> str:
        return self.subtipo or self.error_type

    @property
    def detector(self) -> str | None:
        """Qué hallazgo tendría que haber salido. `None` si nadie lo comprueba."""
        subtipo = self.subtipo
        if subtipo is not None:
            if subtipo in SUBTIPOS_SIN_DETECTOR:
                return None
            if subtipo in DETECTOR_POR_SUBTIPO:
                return DETECTOR_POR_SUBTIPO[subtipo]
        return DETECTOR_POR_ERROR.get(self.error_type)

    @property
    def tiene_detector(self) -> bool:
        """¿Existe la comprobación, aunque no la haya cazado?"""
        return self.detector is not None

    def causa_del_fallo(self) -> str:
        if not self.tiene_detector:
            return SIN_DETECTOR_CONSTRUIDO
        return NO_PUDO_DETERMINARLO if not self.pudo_intentarlo else NO_LO_CAZO


@dataclass(frozen=True)
class Hallazgo:
    """Lo que el motor emitió sobre una partida."""

    partida_id: str
    finding_type: str


@dataclass(frozen=True)
class Conteo:
    """Los cuatro números, y lo que se deriva de ellos."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> Decimal | None:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> Decimal | None:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> Decimal | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return (2 * p * r / (p + r)).quantize(_DOS)

    @property
    def margen_95(self) -> Decimal | None:
        """Media anchura del intervalo de Wilson sobre el recall, en puntos.

        Con seis casos sale enorme a propósito: enseñarlo es lo que impide
        presentar «66 %» como si midiera algo.
        """
        return _wilson(self.tp, self.tp + self.fn)


@dataclass
class Reporte:
    """Detección medida, con sus límites a la vista."""

    agregado: Conteo = field(default_factory=Conteo)
    por_tipo: dict[str, Conteo] = field(default_factory=dict)

    eventos_totales: int = 0
    eventos_medibles: int = 0
    excluidos_por_indetectables: int = 0
    """`expected_detection = false`: fuera del recall, y dicho."""
    excluidos_sin_detector: dict[str, int] = field(default_factory=dict)
    """Tipos que el motor no sabe detectar todavía. No es fallar: es faltar."""

    fn_por_causa: dict[str, int] = field(default_factory=dict)
    """Los tres porqués de un falso negativo, contados por separado."""

    partidas_limpias: int = 0
    falsos_positivos_de_revision: int = 0
    """De los FP, cuántos son el hallazgo de origen, que pide revisión."""
    hallazgos_fuera_de_su_anomalia: int = 0
    """En partidas con anomalía, hallazgos de un tipo que nadie sembró.

    No es ruido: suele ser una cascada real. Una partida con el valor en aduana
    alterado también desvía su IGI y su IVA, y una con la fracción equivocada
    delata que el IGI impreso no corresponde a la tasa de la declarada.
    """

    partidas_con_anomalia: int = 0
    partidas_senaladas: int = 0
    """De ellas, cuántas recibieron AL MENOS un hallazgo, del tipo que sea.

    Detectar por tipo y señalar la partida son cosas distintas, y las dos
    importan: a quien audita le sirve que la partida salga marcada aunque el
    motivo que la marcó no sea el que la ensució.
    """

    @property
    def cobertura_por_partida(self) -> Decimal | None:
        """Qué proporción de partidas sucias quedó señalada por algo."""
        return _ratio(self.partidas_senaladas, self.partidas_con_anomalia)

    @property
    def tasa_falsos_positivos(self) -> Decimal | None:
        """Sobre las partidas limpias. El número que más duele y más importa."""
        return _ratio(self.agregado.fp, self.partidas_limpias)


def _ratio(parte: int, total: int) -> Decimal | None:
    """Porcentaje, o `None` si no hay denominador. `None` no es cero."""
    if total <= 0:
        return None
    return (Decimal(parte) / Decimal(total) * _CIEN).quantize(_DOS)


def _wilson(exitos: int, total: int) -> Decimal | None:
    if total <= 0:
        return None
    p = exitos / total
    denominador = 1 + _Z**2 / total
    mitad = _Z * math.sqrt(p * (1 - p) / total + _Z**2 / (4 * total**2)) / denominador
    return (Decimal(mitad) * _CIEN).quantize(_DOS)


def evaluar(
    eventos: Iterable[Evento],
    hallazgos: Iterable[Hallazgo],
    *,
    partidas: Sequence[str],
) -> Reporte:
    """Compara lo sembrado con lo encontrado.

    `partidas` son TODAS las partidas del corpus: las que no tienen evento son
    las limpias, y son las que miden los falsos positivos.
    """
    eventos = list(eventos)
    hallazgos = list(hallazgos)

    emitidos: set[tuple[str, str]] = {(h.partida_id, h.finding_type) for h in hallazgos}
    con_anomalia = {e.partida_id for e in eventos}
    limpias = [p for p in partidas if p not in con_anomalia]

    # Medible = alguien PODRÍA detectarlo con el documento (`detectable`). Que
    # el detector exista o no es otra cosa, y se cuenta aparte: un recall que
    # excluyera lo no construido escondería justo lo que falta por construir.
    medibles = [e for e in eventos if e.detectable]
    sin_detector: dict[str, int] = defaultdict(int)
    for e in medibles:
        if not e.tiene_detector:
            sin_detector[e.etiqueta] += 1

    por_tipo: dict[str, Conteo] = {}
    causas: dict[str, int] = defaultdict(int)
    tp_total = fn_total = 0
    for evento in medibles:
        esperado = evento.detector
        detectado = esperado is not None and (evento.partida_id, esperado) in emitidos
        if not detectado:
            causas[evento.causa_del_fallo()] += 1
        actual = por_tipo.get(evento.etiqueta, Conteo())
        por_tipo[evento.etiqueta] = Conteo(
            tp=actual.tp + int(detectado),
            fn=actual.fn + int(not detectado),
            fp=actual.fp,
            tn=actual.tn,
        )
        tp_total += int(detectado)
        fn_total += int(not detectado)

    # Falsos positivos: lo emitido sobre partidas declaradas limpias.
    en_limpias = [h for h in hallazgos if h.partida_id in set(limpias)]
    fp_total = len(en_limpias)
    de_revision = sum(1 for h in en_limpias if h.finding_type == HALLAZGO_DE_REVISION)
    con_hallazgo = {h.partida_id for h in en_limpias}
    tn_total = len(limpias) - len(con_hallazgo)

    esperados_por_partida: dict[str, set[str]] = defaultdict(set)
    for e in eventos:
        if e.detector is not None:
            esperados_por_partida[e.partida_id].add(e.detector)
    fuera = sum(
        1
        for h in hallazgos
        if h.partida_id in con_anomalia
        and h.finding_type not in esperados_por_partida[h.partida_id]
    )

    senaladas = {h.partida_id for h in hallazgos} & con_anomalia

    return Reporte(
        agregado=Conteo(tp=tp_total, fp=fp_total, fn=fn_total, tn=tn_total),
        partidas_con_anomalia=len(con_anomalia),
        partidas_senaladas=len(senaladas),
        por_tipo=por_tipo,
        eventos_totales=len(eventos),
        eventos_medibles=len(medibles),
        fn_por_causa=dict(causas),
        excluidos_por_indetectables=sum(1 for e in eventos if not e.detectable),
        excluidos_sin_detector=dict(sin_detector),
        partidas_limpias=len(limpias),
        falsos_positivos_de_revision=de_revision,
        hallazgos_fuera_de_su_anomalia=fuera,
    )
