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


def test_un_tipo_sin_detector_no_cuenta_como_fallo_del_motor() -> None:
    """No haberlo construido no es fallar. El reporte lo nombra aparte."""
    r = evaluar(
        [Evento("p000", "WRONG_UNIT", detectable=True)],
        [],
        partidas=_partidas(1),
    )

    assert r.eventos_medibles == 0
    assert r.excluidos_sin_detector == {"WRONG_UNIT": 1}
    assert r.agregado.recall is None, "sin nada medible es desconocido, no cero"


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
