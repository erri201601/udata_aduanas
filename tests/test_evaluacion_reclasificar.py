"""`clasificacion_39 --reclasificar`: el motor del árbol, sin confirmar nada (ADR 0025)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import apps.api.clasificacion as clasificacion
import apps.api.dna as dna
import database.repositories.classification as repo
import pytest
from apps.evaluacion import clasificacion_39

pytestmark = pytest.mark.unit


class SesionFalsa:
    def __init__(self, filas: list[tuple[str, date]]) -> None:
        self._filas = filas
        self.flushes = 0
        self.commits = 0

    def execute(self, _sentencia: Any) -> Any:
        return SimpleNamespace(all=lambda: self._filas)

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:  # pragma: no cover — si se llama, el test falla
        self.commits += 1


def test_reclasifica_por_el_camino_del_endpoint_y_no_confirma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guardadas: list[dict[str, Any]] = []
    monkeypatch.setattr(
        dna,
        "version_vigente",
        lambda _s, p: None if p == "sin-ficha" else SimpleNamespace(id=f"dna-{p}"),
    )
    monkeypatch.setattr(dna, "cargar_borrador", lambda _s, p: f"borrador-{p}")
    monkeypatch.setattr(
        clasificacion,
        "clasificar_borrador",
        lambda _s, b, **kw: SimpleNamespace(outcome=("resultado", b, kw["operation_date"])),
    )
    monkeypatch.setattr(
        repo, "save_classification", lambda _s, o, **kw: guardadas.append({"outcome": o, **kw})
    )
    sesion = SesionFalsa([("a", date(2026, 8, 3)), ("sin-ficha", date(2026, 8, 3))])

    hechas = clasificacion_39.reclasificar(sesion)  # type: ignore[arg-type]

    assert hechas == 1
    assert guardadas == [
        {
            "outcome": ("resultado", "borrador-a", date(2026, 8, 3)),
            "product_id": "a",
            "product_dna_id": "dna-a",
            "trade_flow": "IMPORT",
        }
    ]
    assert sesion.flushes == 1
    assert sesion.commits == 0
