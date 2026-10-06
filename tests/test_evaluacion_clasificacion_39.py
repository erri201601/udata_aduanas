"""La medición de precisión del §39, y contra qué mide.

LO QUE ESTE FICHERO PROTEGE

La verdad contra la que se mide no es siempre la fracción declarada. Una
declaración «limpia» del corpus la escribió el generador sintético; un
dictamen lo firmó un clasificador. Cuando los dos existen y discrepan, manda
el dictamen.

Sin eso, la métrica llamó error al acierto catorce veces el 6 de octubre: un
clasificador contestó que un cable 6x36 no cumple «constituidos por 7
alambres», el motor pasó a resolver `73121005` —la misma fracción que dice su
dictamen escrito— y las catorce partidas declaran `73121099`.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.evaluacion.clasificacion_39 import medir

pytestmark = pytest.mark.unit


def _fila(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "sku": "PED_SIM_001-004",
        "declarada": "73121099",
        "propuesta": "73121005",
        "dictamen": None,
        "hubo_decision": True,
    }
    base.update(kw)
    return type("Fila", (), base)()


class SesionDeFilas:
    def __init__(self, filas: list[Any]) -> None:
        self._filas = filas

    def execute(self, _consulta: Any) -> Any:
        r = type("R", (), {})()
        r.all = lambda: list(self._filas)
        return r


def test_el_dictamen_humano_manda_sobre_la_declaracion() -> None:
    """El caso real: la declaración dice 73121099 y el clasificador 73121005.

    El motor propone 73121005. Es un ACIERTO, no un fallo.
    """
    r = medir(SesionDeFilas([_fila(dictamen="73121005")]))  # type: ignore[arg-type]

    assert r.acerto == 1
    assert r.fallo == 0
    assert r.contra_dictamen == 1
    assert r.contra_declaracion == 0


def test_sin_dictamen_se_mide_contra_la_declaracion() -> None:
    """No se inventa una verdad humana donde no la hay."""
    r = medir(SesionDeFilas([_fila(dictamen=None)]))  # type: ignore[arg-type]

    assert r.fallo == 1
    assert r.contra_declaracion == 1
    assert r.contra_dictamen == 0


def test_el_dictamen_tambien_puede_declarar_un_fallo() -> None:
    """Que mande el dictamen no significa que el motor acierte siempre.

    Si el clasificador dice una fracción y el motor dice otra, es un fallo —y
    uno que vale más que un fallo contra la declaración, porque lo firma una
    persona.
    """
    r = medir(SesionDeFilas([_fila(dictamen="73121008")]))  # type: ignore[arg-type]

    assert r.fallo == 1
    assert r.contra_dictamen == 1
    assert r.errores[0][1] == "73121008"
    assert r.errores[0][3] == "dictamen"


def test_el_informe_dice_contra_que_midio_cada_una() -> None:
    """Un porcentaje sin su fuente de verdad no se puede interpretar.

    100 % contra una declaración sintética y 100 % contra el dictamen de un
    clasificador son dos afirmaciones muy distintas, y el número solo no las
    distingue.
    """
    from apps.evaluacion.clasificacion_39 import informe

    r = medir(  # type: ignore[arg-type]
        SesionDeFilas(
            [
                _fila(sku="con-dictamen", dictamen="73121005"),
                _fila(sku="sin-dictamen", propuesta="73121099"),
            ]
        )
    )
    texto = informe(r)

    assert "contra dictamen: 1" in texto
    assert "contra declaración: 1" in texto


def test_una_abstencion_no_se_mide_contra_nada() -> None:
    """El §8.2 funcionando no es un acierto ni un fallo."""
    r = medir(SesionDeFilas([_fila(propuesta=None, dictamen="73121005")]))  # type: ignore[arg-type]

    assert r.se_abstuvo == 1
    assert r.contestadas == 0
    assert r.contra_dictamen == 0


def test_un_producto_que_nadie_clasifico_no_cuenta() -> None:
    """Nadie se lo pidió al motor: no es una abstención suya."""
    r = medir(SesionDeFilas([_fila(hubo_decision=False, propuesta=None)]))  # type: ignore[arg-type]

    assert r.sin_decision == 1
    assert r.medibles == 0
