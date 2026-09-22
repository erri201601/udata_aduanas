"""Tests de la métrica de detección del §26.

Los que importan son los que impiden que el número engañe: que lo indetectable
salga del recall, que el NICO no se presente como una sola capacidad, y que los
falsos positivos se cuenten sobre las partidas limpias.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from core.evaluation.deteccion import (
    DETECTOR_POR_ERROR,
    NICO_EXIGE_FICHA,
    NICO_LO_CAZA_EL_CATALOGO,
    SIN_DETECTOR,
    Evento,
    Hallazgo,
    evaluar,
)

pytestmark = pytest.mark.unit


def _partidas(n: int) -> list[str]:
    return [f"p{i:03d}" for i in range(n)]


def test_un_evento_detectado_es_tp_y_uno_perdido_es_fn() -> None:
    r = evaluar(
        [
            Evento("p000", "WRONG_ORIGIN", detectable=True),
            Evento("p001", "WRONG_VALUE", detectable=True),
        ],
        [Hallazgo("p000", "ORIGIN_MISMATCH")],
        partidas=_partidas(2),
    )

    assert (r.agregado.tp, r.agregado.fn) == (1, 1)
    assert r.agregado.recall == Decimal("50.00")


def test_lo_indetectable_sale_del_recall_y_se_dice() -> None:
    """EL TEST QUE IMPORTA.

    Las seis de cantidad no las puede detectar nadie con lo que trae el
    documento. Contarlas como fallos del motor sería medir otra cosa.
    """
    eventos = [Evento(f"p{i:03d}", "INCONSISTENT_QUANTITY", detectable=False) for i in range(6)]
    eventos.append(Evento("p010", "WRONG_ORIGIN", detectable=True))

    r = evaluar(eventos, [Hallazgo("p010", "ORIGIN_MISMATCH")], partidas=_partidas(11))

    assert r.eventos_totales == 7
    assert r.eventos_medibles == 1
    assert r.excluidos_por_indetectables == 6
    assert r.agregado.recall == Decimal("100.00"), "el recall no carga con lo imposible"


def test_un_tipo_sin_detector_cuenta_pero_con_su_causa_escrita() -> None:
    """EL TEST QUE IMPORTA (Persona 1, 22-sep).

    El ejemplo era MISSING_TECHNICAL_FIELD y dejó de servir el 22-sep: ese
    detector ya existe. Se cambió por uno que sigue sin construirse, no por
    uno que dé verde.

    No haberlo construido no es fallar, pero tampoco se saca del denominador:
    un recall que escondiera lo no construido presentaría como bueno un
    sistema al que le falta medio detector. Cuenta, y dice por qué.
    """
    from core.evaluation.deteccion import SIN_DETECTOR_CONSTRUIDO

    r = evaluar(
        [Evento("p000", "INCONSISTENT_QUANTITY", detectable=True)], [], partidas=_partidas(1)
    )

    assert r.eventos_medibles == 1
    assert r.agregado.recall == Decimal("0.00")
    assert r.excluidos_sin_detector == {"INCONSISTENT_QUANTITY": 1}
    assert r.fn_por_causa == {SIN_DETECTOR_CONSTRUIDO: 1}


def test_los_tres_porques_de_un_falso_negativo_se_separan() -> None:
    """Se ven iguales en la tabla y no son lo mismo."""
    from core.evaluation.deteccion import (
        NO_LO_CAZO,
        NO_PUDO_DETERMINARLO,
        SIN_DETECTOR_CONSTRUIDO,
    )

    r = evaluar(
        [
            Evento("p000", "INCONSISTENT_QUANTITY", detectable=True),
            Evento("p001", "WRONG_FRACTION", detectable=True, pudo_intentarlo=False),
            Evento("p002", "WRONG_ORIGIN", detectable=True),
        ],
        [],
        partidas=_partidas(3),
    )

    assert r.fn_por_causa == {
        SIN_DETECTOR_CONSTRUIDO: 1,
        NO_PUDO_DETERMINARLO: 1,
        NO_LO_CAZO: 1,
    }


def test_los_cuatro_sabores_de_valor_no_se_presentan_como_uno() -> None:
    """El corpus colapsa cuatro anomalías en WRONG_VALUE. Sólo una tiene detector."""
    from core.evaluation.deteccion import SUBTIPO_POR_CAMPO

    eventos = [
        Evento("p000", "WRONG_VALUE", detectable=True, subtipo=SUBTIPO_POR_CAMPO["customs_value"]),
        Evento("p001", "WRONG_VALUE", detectable=True, subtipo=SUBTIPO_POR_CAMPO["igi_rate"]),
    ]
    r = evaluar(eventos, [Hallazgo("p000", "VALUE_MISMATCH")], partidas=_partidas(2))

    assert r.por_tipo["WRONG_VALUE/valor en aduana"].recall == Decimal("100.00")
    assert r.por_tipo["WRONG_VALUE/tasa de IGI"].recall == Decimal("0.00")
    assert "WRONG_VALUE" not in r.por_tipo


def test_el_nico_se_reporta_en_dos_filas() -> None:
    """Son capacidades distintas: juntarlas da una cifra que no significa nada."""
    r = evaluar(
        [
            Evento("p000", "WRONG_NICO", detectable=True, subtipo=NICO_LO_CAZA_EL_CATALOGO),
            Evento("p001", "WRONG_NICO", detectable=True, subtipo=NICO_EXIGE_FICHA),
        ],
        [Hallazgo("p000", "NICO_MISMATCH")],
        partidas=_partidas(2),
    )

    assert r.por_tipo[NICO_LO_CAZA_EL_CATALOGO].recall == Decimal("100.00")
    assert r.por_tipo[NICO_EXIGE_FICHA].recall == Decimal("0.00")
    assert "WRONG_NICO" not in r.por_tipo, "sin la fila mezclada que engaña"


def test_los_falsos_positivos_se_cuentan_sobre_las_limpias() -> None:
    """Un sistema que grita en todas detecta todo y no sirve."""
    r = evaluar(
        [Evento("p000", "WRONG_ORIGIN", detectable=True)],
        [Hallazgo("p000", "ORIGIN_MISMATCH"), Hallazgo("p005", "VALUE_MISMATCH")],
        partidas=_partidas(10),
    )

    assert r.partidas_limpias == 9
    assert r.agregado.fp == 1
    assert r.agregado.tn == 8
    assert r.tasa_falsos_positivos == Decimal("11.11")


def test_los_falsos_positivos_de_origen_se_reportan_aparte() -> None:
    """Piden revisión humana, no acusan. Siguen siendo ruido, pero se separan."""
    r = evaluar(
        [],
        [Hallazgo("p001", "ORIGIN_MISMATCH"), Hallazgo("p002", "FRACTION_MISMATCH")],
        partidas=_partidas(5),
    )

    assert r.agregado.fp == 2
    assert r.falsos_positivos_de_revision == 1


def test_un_hallazgo_de_otro_tipo_en_partida_sembrada_se_cuenta_aparte() -> None:
    r = evaluar(
        [Evento("p000", "WRONG_ORIGIN", detectable=True)],
        [Hallazgo("p000", "ORIGIN_MISMATCH"), Hallazgo("p000", "VALUE_MISMATCH")],
        partidas=_partidas(3),
    )

    assert r.agregado.tp == 1
    assert r.hallazgos_fuera_de_su_anomalia == 1
    assert r.agregado.fp == 0, "no es una partida limpia"


def test_con_seis_casos_el_margen_es_enorme_y_se_enseña() -> None:
    """Sirve para ver si un tipo falla del todo, no para afirmar un porcentaje."""
    eventos = [Evento(f"p{i:03d}", "WRONG_ORIGIN", detectable=True) for i in range(6)]
    hallazgos = [Hallazgo(f"p{i:03d}", "ORIGIN_MISMATCH") for i in range(3)]

    r = evaluar(eventos, hallazgos, partidas=_partidas(6))

    assert r.agregado.recall == Decimal("50.00")
    assert r.agregado.margen_95 is not None
    assert r.agregado.margen_95 > Decimal("30"), "con n=6 no se puede afirmar un porcentaje"


def test_sin_partidas_limpias_la_tasa_es_desconocida_no_cero() -> None:
    r = evaluar([Evento("p000", "WRONG_ORIGIN", detectable=True)], [], partidas=["p000"])

    assert r.tasa_falsos_positivos is None


def test_el_mapeo_cubre_el_vocabulario_de_los_dos_lados() -> None:
    """Los dos son cerrados: si alguien añade un tipo, esto lo detecta."""
    from core.shadow.divergences import DivergenceType
    from database.models.enums import ERROR_TYPE

    assert set(DETECTOR_POR_ERROR) <= set(ERROR_TYPE)
    assert set(ERROR_TYPE) >= SIN_DETECTOR
    assert set(DETECTOR_POR_ERROR) | SIN_DETECTOR == set(ERROR_TYPE), (
        "hay tipos de error que no están ni mapeados ni declarados sin detector"
    )
    assert set(DETECTOR_POR_ERROR.values()) <= {d.value for d in DivergenceType}


def test_no_se_empareja_por_nombre_de_campo() -> None:
    """El ground truth dice `tariff_fraction` y el motor emite `fraction_code`.

    Emparejar por esa cadena habría dado cero sin que nada fallara.
    """
    r = evaluar(
        [Evento("p000", "WRONG_FRACTION", detectable=True)],
        [Hallazgo("p000", "FRACTION_MISMATCH")],
        partidas=["p000"],
    )

    assert r.agregado.tp == 1


def test_la_cobertura_por_partida_se_reporta_aparte_de_la_deteccion_por_tipo() -> None:
    """Señalar la partida y diagnosticar la anomalía son cosas distintas.

    Una fracción equivocada puede quedar señalada porque su IGI no cuadra con
    la tasa de la fracción declarada. No la diagnostica —el tipo no coincide—
    pero a quien audita le sirve que la partida salga marcada.
    """
    r = evaluar(
        [Evento("p000", "WRONG_FRACTION", detectable=True)],
        [Hallazgo("p000", "IGI_RATE_MISMATCH")],
        partidas=_partidas(5),
    )

    assert r.agregado.tp == 0, "no se diagnosticó la fracción"
    assert r.partidas_senaladas == 1, "pero la partida quedó marcada"
    assert r.cobertura_por_partida == Decimal("100.00")
    assert r.hallazgos_fuera_de_su_anomalia == 1


# ── Un hallazgo cierto no es un falso positivo (Persona 1, 22-sep) ───────────


def test_la_ficha_recortada_por_el_corpus_no_cuenta_como_falso_positivo() -> None:
    """El corpus recortó la ficha a propósito sin sembrar el evento.

    El detector acierta: la ficha está incompleta de verdad. Contarlo como
    falso positivo mediría una decisión del corpus, no el motor.
    """
    r = evaluar(
        [Evento("p000", "MISSING_TECHNICAL_FIELD", detectable=True)],
        [Hallazgo("p000", "MISSING_TECHNICAL_FIELD"), Hallazgo("p001", "MISSING_TECHNICAL_FIELD")],
        partidas=_partidas(3),
        condiciones_sembradas={("p001", "MISSING_TECHNICAL_FIELD")},
    )

    assert r.agregado.tp == 1, "el sembrado sí se cuenta"
    assert r.agregado.fp == 0, "el otro es cierto, no falso"
    assert r.condiciones_sembradas_no_contadas == 1, "y se declara"
    assert r.agregado.precision == Decimal("100.00")


def test_la_partida_excluida_sigue_siendo_control_limpio_de_los_demas() -> None:
    """Se excluye el par (partida, tipo), no la partida.

    Si se excluyera la partida entera, un hallazgo de origen inventado sobre
    ella dejaría de verse, y ése sí es ruido.
    """
    r = evaluar(
        [],
        [Hallazgo("p000", "MISSING_TECHNICAL_FIELD"), Hallazgo("p000", "ORIGIN_MISMATCH")],
        partidas=_partidas(2),
        condiciones_sembradas={("p000", "MISSING_TECHNICAL_FIELD")},
    )

    assert r.agregado.fp == 1, "el de origen sí es falso positivo"
    assert r.falsos_positivos_de_revision == 1
    assert r.condiciones_sembradas_no_contadas == 1
    assert r.partidas_limpias == 2, "la partida no sale de la población limpia"


def test_re_auditar_el_mismo_pedimento_no_multiplica_los_falsos_positivos() -> None:
    """Cada re-auditoría deja su copia del hallazgo en la base.

    Sin deduplicar, el mismo ruido contado cuatro veces daría una precisión
    peor cada vez que alguien vuelve a medir, que no es una propiedad del
    motor.
    """
    repetido = [Hallazgo("p000", "ORIGIN_MISMATCH")] * 4
    r = evaluar([], repetido, partidas=_partidas(4))

    assert r.agregado.fp == 1
    assert r.agregado.tn == 3
