"""§39 «HS accuracy» y «human review rate» en la medición de clasificación."""

from __future__ import annotations

from typing import Any

import pytest
from apps.evaluacion.clasificacion_39 import informe, medir

pytestmark = pytest.mark.unit


def _fila(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "sku": "S",
        "declarada": "73121099",
        "propuesta": "73121099",
        "dictamen": None,
        "sin_fundamento": False,
        "hubo_decision": True,
        "revision_humana": False,
        "dictamen_nico": None,
        "declarada_nico": None,
        "fecha": None,
    }
    base.update(kw)
    return type("Fila", (), base)()


class _Sesion:
    def __init__(self, filas: list[Any]) -> None:
        self._filas = filas

    def execute(self, _consulta: Any) -> Any:
        r = type("R", (), {})()
        r.all = lambda: list(self._filas)
        return r


def test_acertar_la_subpartida_y_fallar_la_apertura_cuenta_para_hs() -> None:
    r = medir(_Sesion([_fila(propuesta="73121005")]))  # type: ignore[arg-type]
    assert (r.acerto, r.fallo) == (0, 1)
    assert (r.hs_acerto, r.hs_fallo) == (1, 0), "7312.10 es la misma subpartida"


def test_otro_capitulo_falla_tambien_en_hs() -> None:
    r = medir(_Sesion([_fila(propuesta="85442001")]))  # type: ignore[arg-type]
    assert (r.hs_acerto, r.hs_fallo) == (0, 1)


def test_la_revision_humana_se_cuenta_sobre_las_medibles() -> None:
    r = medir(
        _Sesion(  # type: ignore[arg-type]
            [
                _fila(revision_humana=True),
                _fila(propuesta=None, revision_humana=True),
                _fila(),
                _fila(hubo_decision=False, propuesta=None, revision_humana=True),
            ]
        )
    )
    assert r.medibles == 3, "la que nunca se clasificó no es medible"
    assert r.revision_humana == 2
    assert str(r.tasa_revision_humana) == "66.67"
    texto = informe(r)
    assert "HS (6 dígitos)" in texto and "REVISIÓN HUMANA  66.67 %" in texto
