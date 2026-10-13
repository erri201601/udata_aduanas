"""Identificadores exigidos en el Espejo (ADR 0012, §20).

Lo que se protege: que un identificador de pedimento se distinga de uno de
partida —se cuenta una vez por documento—, que «no hay reglas» no se confunda
con «no exige ninguno», y que la regla del NICO pida fracción y NICO juntos.
"""

from __future__ import annotations

import pytest
from core.shadow import DeclaredItem, DivergenceType, ExpectedItem, compare
from core.shadow.compare import (
    CAMPO_IDENTIFICADORES_DEL_DOCUMENTO,
    _lagunas,
    comprobaciones_hechas,
)
from database.repositories.identificadores import ReglasDeIdentificadores

pytestmark = pytest.mark.unit


def _identificadores(**kw: object) -> list:  # type: ignore[type-arg]
    declarada = DeclaredItem(line_number=1, **kw.pop("declarada", {}))  # type: ignore[arg-type]
    esperada = ExpectedItem(line_number=1, **kw)  # type: ignore[arg-type]
    return [
        d
        for d in compare([declarada], [esperada]).divergences
        if d.kind is DivergenceType.IDENTIFIER_MISMATCH
    ]


# ── El Espejo ────────────────────────────────────────────────────────────────


def test_falta_un_identificador_del_pedimento() -> None:
    [d] = _identificadores(required_document_identifiers=("V1",))
    assert d.field == CAMPO_IDENTIFICADORES_DEL_DOCUMENTO
    assert d.expected_value == "V1"
    assert "en el pedimento" in d.reasoning


def test_declarado_en_el_pedimento_no_es_hallazgo() -> None:
    assert (
        _identificadores(
            required_document_identifiers=("V1",),
            declarada={"document_identifiers": {"V1": {}}},
        )
        == []
    )


def test_declararlo_en_la_partida_no_cubre_el_del_pedimento() -> None:
    """Son dos sitios distintos del documento; el Apéndice 8 dice cuál."""
    [d] = _identificadores(
        required_document_identifiers=("V1",),
        declarada={"identifiers": {"V1": {}}},
    )
    assert d.field == CAMPO_IDENTIFICADORES_DEL_DOCUMENTO


def test_falta_un_identificador_de_partida() -> None:
    [d] = _identificadores(required_identifiers=("ME",))
    assert d.field == "identifiers"


def test_con_reglas_y_ninguna_aplica_se_cuenta_como_comprobado() -> None:
    esperada = ExpectedItem(
        line_number=1, required_identifiers=(), required_document_identifiers=()
    )
    assert "identificadores" in comprobaciones_hechas(esperada)
    assert not any("identificadores" in r for r in _lagunas(esperada))


def test_sin_reglas_es_una_laguna_y_no_una_comprobacion() -> None:
    esperada = ExpectedItem(line_number=1)
    assert "identificadores" not in comprobaciones_hechas(esperada)
    assert any("identificadores" in r for r in _lagunas(esperada))


def test_basta_con_saber_los_del_pedimento_para_contar_la_comprobacion() -> None:
    esperada = ExpectedItem(line_number=1, required_document_identifiers=("V1",))
    assert "identificadores" in comprobaciones_hechas(esperada)


# ── Las reglas ───────────────────────────────────────────────────────────────

REGLAS = ReglasDeIdentificadores(
    reglas=(
        ("V1", "G", "PEDIMENTO_KEY", "V1"),
        ("ME", "P", "NICO", "9803000101"),
        ("XX", "P", "FRACTION", "87032301"),
    )
)


def test_la_clave_de_pedimento_exige_el_suyo_en_el_documento() -> None:
    exigidos = REGLAS.para(pedimento_key="V1", fraction_code="85285901", nico_code="00")
    assert exigidos.del_documento == ("V1",)
    assert exigidos.de_la_partida == ()


def test_la_regla_de_nico_pide_fraccion_y_nico_juntos() -> None:
    assert REGLAS.para(
        pedimento_key="A1", fraction_code="98030001", nico_code="01"
    ).de_la_partida == ("ME",)
    assert (
        REGLAS.para(pedimento_key="A1", fraction_code="98030001", nico_code="02").de_la_partida
        == ()
    )
    assert (
        REGLAS.para(pedimento_key="A1", fraction_code="98030001", nico_code=None).de_la_partida
        == ()
    )


def test_la_regla_de_fraccion() -> None:
    assert REGLAS.para(
        pedimento_key=None, fraction_code="87032301", nico_code=None
    ).de_la_partida == ("XX",)


def test_una_operacion_a1_comun_no_exige_ninguno_de_los_estructurables() -> None:
    exigidos = REGLAS.para(pedimento_key="A1", fraction_code="85285901", nico_code="00")
    assert exigidos.del_documento == () and exigidos.de_la_partida == ()
