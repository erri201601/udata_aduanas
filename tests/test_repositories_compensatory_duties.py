"""Tests de `database.repositories.compensatory_duties.normalizar_nombre`
(ADR 0009) -- la coincidencia EXACTA normalizada contra
`operational.suppliers.legal_name`, nunca aproximada (decisión de
Persona 1, 6-oct: una coincidencia parecida le daría a alguien la tasa de
un exportador nombrado por error, que sería inventar una exención)."""

from __future__ import annotations

import pytest
from database.repositories.compensatory_duties import normalizar_nombre

pytestmark = pytest.mark.unit


def test_mayusculas_espacios_y_puntuacion_no_importan() -> None:
    assert normalizar_nombre("Oriental Technical Supply Co. Ltd.") == normalizar_nombre(
        "ORIENTAL TECHNICAL SUPPLY CO LTD"
    )


def test_espacios_dobles_colapsan() -> None:
    assert normalizar_nombre("Oriental   Technical  Supply") == normalizar_nombre(
        "Oriental Technical Supply"
    )


def test_un_nombre_distinto_no_coincide() -> None:
    """Quitar "Ltd." no es normalizar un formato -- es un nombre distinto."""
    assert normalizar_nombre("Oriental Technical Supply Co. Ltd.") != normalizar_nombre(
        "Oriental Technical Supply Co."
    )
