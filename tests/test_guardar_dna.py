"""`guardar_dna`: la ficha y cada atributo apuntan a su evidencia (13-oct).

Y la guarda de siempre: una extracción que no encontró nada no sustituye a una
ficha buena. Con el motor devolviendo siempre el catálogo completo, esa guarda
tiene que mirar los atributos CONOCIDOS, no todos.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from core.evidence.builder import model_output
from core.product_dna.types import ExtractedAttribute, ProductDnaDraft
from database.models.intelligence import EvidenceRecord, ProductAttribute, ProductDna
from database.repositories.product_dna import guardar_dna

pytestmark = pytest.mark.unit


class _Sesion:
    def __init__(self) -> None:
        self.filas: list[Any] = []
        self.actualizaciones = 0

    def scalar(self, _s: Any) -> Any:
        return 3  # ya había tres versiones

    def execute(self, _s: Any) -> None:
        self.actualizaciones += 1

    def add(self, fila: Any) -> None:
        fila.id = getattr(fila, "id", None) or uuid.uuid4()
        self.filas.append(fila)

    def flush(self) -> None: ...

    def de(self, tipo: type) -> list[Any]:
        return [f for f in self.filas if isinstance(f, tipo)]


def _evidencia() -> Any:
    return model_output(
        summary="Product DNA extraído de PDF: ficha.pdf",
        model_provider="fake",
        model_name="fake-1",
        prompt_id="product_dna.extract",
        prompt_version="0.2",
    )


def _borrador(*atributos: ExtractedAttribute) -> ProductDnaDraft:
    return ProductDnaDraft(attributes=atributos, input_kinds=("pdf",))


ACERO = ExtractedAttribute(
    name="materials", value="acero", status="EXTRACTED", locator="[p.2] Materiales"
)
VOLTAJE = ExtractedAttribute(
    name="voltage", value="127", status="INFERRED", confidence=Decimal("0.5")
)
SIN_DATO = ExtractedAttribute(name="power", status="MISSING")


def test_la_ficha_y_sus_atributos_apuntan_a_la_misma_evidencia() -> None:
    sesion = _Sesion()
    dna = guardar_dna(
        sesion,  # type: ignore[arg-type]
        _borrador(ACERO, VOLTAJE),
        product_id=uuid.uuid4(),
        data_origin="SYNTHETIC",
        evidencia=_evidencia(),
    )

    [registro] = sesion.de(EvidenceRecord)
    assert registro.evidence_kind == "MODEL_OUTPUT"
    assert registro.subject_kind == "product_dna"
    assert registro.subject_id == dna.id
    assert registro.data_origin == "SYNTHETIC"
    assert dna.evidence_id == registro.id
    assert {a.evidence_reference for a in sesion.de(ProductAttribute)} == {registro.id}


def test_el_localizador_se_guarda() -> None:
    """Estaba en memoria y se perdía al guardar."""
    sesion = _Sesion()
    guardar_dna(
        sesion,  # type: ignore[arg-type]
        _borrador(ACERO),
        product_id=uuid.uuid4(),
        data_origin="SYNTHETIC",
        evidencia=_evidencia(),
    )

    [atributo] = sesion.de(ProductAttribute)
    assert atributo.locator == "[p.2] Materiales"


def test_lo_que_falta_no_apunta_a_la_evidencia() -> None:
    """Un MISSING no salió del documento: enlazarlo diría que el archivo lo
    respalda."""
    sesion = _Sesion()
    guardar_dna(
        sesion,  # type: ignore[arg-type]
        _borrador(ACERO, SIN_DATO),
        product_id=uuid.uuid4(),
        data_origin="SYNTHETIC",
        evidencia=_evidencia(),
    )

    por_nombre = {a.name: a for a in sesion.de(ProductAttribute)}
    assert por_nombre["materials"].evidence_reference is not None
    assert por_nombre["power"].evidence_reference is None


def test_una_extraccion_que_solo_trae_ausentes_no_sustituye_a_la_ficha() -> None:
    """El motor devuelve el catálogo entero: 18 MISSING no son 18 atributos."""
    sesion = _Sesion()
    dna = guardar_dna(
        sesion,  # type: ignore[arg-type]
        _borrador(SIN_DATO, ExtractedAttribute(name="voltage", status="MISSING")),
        product_id=uuid.uuid4(),
        data_origin="SYNTHETIC",
        evidencia=_evidencia(),
    )

    assert dna.is_current is False
    assert dna.version == 4, "se guarda igual: el intento ocurrió y consta"
    assert sesion.actualizaciones == 0, "y la ficha vigente no se tocó"


def test_una_extraccion_con_algo_conocido_si_la_sustituye() -> None:
    sesion = _Sesion()
    dna = guardar_dna(
        sesion,  # type: ignore[arg-type]
        _borrador(ACERO, SIN_DATO),
        product_id=uuid.uuid4(),
        data_origin="SYNTHETIC",
    )

    assert dna.is_current is True
    assert sesion.actualizaciones == 1


def test_sin_evidencia_no_se_inventa_ninguna() -> None:
    sesion = _Sesion()
    dna = guardar_dna(
        sesion,  # type: ignore[arg-type]
        _borrador(ACERO),
        product_id=uuid.uuid4(),
        data_origin="SYNTHETIC",
    )

    assert sesion.de(EvidenceRecord) == []
    assert dna.evidence_id is None
    assert isinstance(dna, ProductDna)
