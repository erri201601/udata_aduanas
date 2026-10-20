"""Las reglas «clave de pedimento → identificador» del Apéndice 8 (ADR 0012).

Lo que se protege: que una regla sólo se cargue si el texto del documento la
sostiene, incluso cuando `pdftotext -layout` intercala otra columna en medio
de la frase, y que una regla equivocada no pase por parecerse.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from database.models.regulatory import PedimentoIdentifierRequirement
from ingestion.dof.apendice_8_requisitos import (
    ParsedIdentifierRequirement,
    requisitos_apendice_8,
    verificar_contra_el_documento,
)

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: Imita el texto `-layout` real: la frase parte de línea y la columna vecina
#: («Declarar la clave que corresponda») cae en medio.
DOCUMENTO = [
    "A3- Regularización   de G    Identificar conforme a los Declarar         la      clave",
    "    mercancías               supuestos de la clave de corresponda, conforme a lo",
    "    (importación             documento A3 del apéndice 2. siguiente:",
    "TD- Tipo de desistimiento G      Conforme a los supuestos de la Declarar      la",
    "    y retorno.                   clave de documento K1 del corresponda:",
    "AF - Activo fijo.          G       Identificar  el   activo  fijo, No asentar datos.",
    "                                   únicamente cuando la clave de",
    "                                   documento no sea exclusiva",
]


@pytest.mark.unit
def test_son_nueve_y_af_no_esta() -> None:
    codigos = [r.identifier_code for r in requisitos_apendice_8()]
    assert len(codigos) == 9
    assert "AF" not in codigos
    assert all(r.identifier_level == "G" for r in requisitos_apendice_8())


@pytest.mark.unit
def test_td_remite_a_k1_no_a_si_misma() -> None:
    [td] = [r for r in requisitos_apendice_8() if r.identifier_code == "TD"]
    assert td.pedimento_key == "K1"


@pytest.mark.unit
def test_la_frase_partida_por_otra_columna_se_reconoce() -> None:
    ok, mal = verificar_contra_el_documento(
        DOCUMENTO, [ParsedIdentifierRequirement("A3", "A3", "…")]
    )
    assert [r.identifier_code for r in ok] == ["A3"]
    assert mal == []


@pytest.mark.unit
def test_una_regla_que_el_documento_no_dice_no_pasa() -> None:
    falsas = [
        ParsedIdentifierRequirement("TD", "TD", "…"),
        ParsedIdentifierRequirement("A3", "K1", "…"),
        ParsedIdentifierRequirement("AF", "A1", "…"),
        ParsedIdentifierRequirement("ZZ", "ZZ", "…"),
    ]
    ok, mal = verificar_contra_el_documento(DOCUMENTO, falsas)
    assert ok == []
    assert len(mal) == 4
    assert all("NEEDS_VALIDATION" in m for m in mal)


@pytest.mark.integration
def test_carga_idempotente_en_el_contrato_del_adr_0012(pg_session: Session) -> None:  # noqa: F811
    from ingestion.dof.load import ANEXO22_VALID_FROM, load_identifier_requirements

    prueba = [ParsedIdentifierRequirement("Y9", "K9", "supuesto de prueba")]
    primera = load_identifier_requirements(pg_session, requisitos=prueba, content_hash="b2" * 32)
    segunda = load_identifier_requirements(pg_session, requisitos=prueba, content_hash="b2" * 32)
    assert (primera, segunda) == (1, 0)

    fila = (
        pg_session.query(PedimentoIdentifierRequirement)
        .filter_by(identifier_code="Y9", condition_value="K9")
        .one()
    )
    assert fila.condition_kind == "PEDIMENTO_KEY"
    assert fila.identifier_level == "G"
    assert fila.scope_note == "supuesto de prueba"
    assert fila.data_origin == "OFFICIAL"
    assert fila.valid_from == ANEXO22_VALID_FROM == date(2026, 1, 15)
