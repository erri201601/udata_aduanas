"""La comprobación previa a la demo: que diga lo que no coincide y no se calle nada."""

from __future__ import annotations

from typing import Any

import pytest
from apps.evaluacion import antes_de_la_demo as demo

pytestmark = pytest.mark.unit


def test_comparar_dice_lo_esperado_y_lo_obtenido() -> None:
    r = demo.comparar("bandeja", 0, 3)
    assert not r.ok
    assert (r.esperado, r.obtenido) == ("0", "3")
    assert demo.comparar("bandeja", 0, 0).ok


def test_si_algo_no_coincide_sale_con_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        demo, "COMPROBACIONES", [("Prueba", lambda _a, _s: [demo.comparar("x", 1, 2)])]
    )
    assert demo.main([]) == 1


def test_todo_en_orden_sale_bien(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(
        demo, "COMPROBACIONES", [("Prueba", lambda _a, _s: [demo.comparar("x", 1, 1)])]
    )
    assert demo.main([]) == 0
    assert "TODO COMO EN EL GUION" in capsys.readouterr().out


def test_una_comprobacion_que_revienta_no_esconde_las_demas(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def revienta(_a: str, _s: Any) -> list[demo.Resultado]:
        raise RuntimeError("sin base")

    monkeypatch.setattr(
        demo,
        "COMPROBACIONES",
        [("Rota", revienta), ("Sana", lambda _a, _s: [demo.comparar("sigue", 1, 1)])],
    )
    assert demo.main([]) == 1
    salida = capsys.readouterr().out
    assert "sin base" in salida
    assert "✓ sigue" in salida
