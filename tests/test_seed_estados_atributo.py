"""Los cuatro estados de atributo tienen que existir en las fixtures.

Sin `INFERRED` ni `MISSING`, la pantalla de Product DNA se construiría sin
haber visto nunca los dos casos que más importan (§16 y §33): el dato del que
hay que desconfiar y el que impide que el sistema invente un valor.

No tocan PostgreSQL: el seed se ejercita con una sesión simulada, igual que
`test_el_seed_solo_produce_filas_sinteticas`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from database.models.enums import ATTRIBUTE_STATUS

pytestmark = pytest.mark.unit


def _filas_del_seed() -> list[Any]:
    from database.seeds.canonical_v0_1 import seed

    session = MagicMock()
    session.scalar.return_value = None
    seed(session)

    filas: list[Any] = [c.args[0] for c in session.add.call_args_list]
    for call in session.add_all.call_args_list:
        filas.extend(call.args[0])
    return filas


def _atributos() -> dict[str, Any]:
    from database.models import ProductAttribute

    return {f.name: f for f in _filas_del_seed() if isinstance(f, ProductAttribute)}


def test_aparecen_los_cuatro_estados() -> None:
    """Los cuatro valores de ATTRIBUTE_STATUS, no sólo los cómodos."""
    estados = {a.status for a in _atributos().values()}

    assert estados == set(ATTRIBUTE_STATUS)


def test_el_inferido_lleva_confianza_baja() -> None:
    """Un dato deducido no puede presentarse con la confianza de uno leído."""
    inferido = next(a for a in _atributos().values() if a.status == "INFERRED")

    assert inferido.confidence is not None
    assert Decimal("0.50") <= inferido.confidence <= Decimal("0.70")


def test_el_faltante_no_tiene_valor_ni_evidencia() -> None:
    """Un dato que no está no tiene respaldo que citar (regla de Persona 1)."""
    faltante = next(a for a in _atributos().values() if a.status == "MISSING")

    assert faltante.value is None
    assert faltante.confidence is None
    assert faltante.evidence_reference is None


def test_el_faltante_se_declara_en_missing_information() -> None:
    """Es lo que dispara la petición de información al importador (§16)."""
    from database.models import ProductAttribute, ProductDna

    filas = _filas_del_seed()
    dna = next(f for f in filas if isinstance(f, ProductDna))
    faltantes = [f.name for f in filas if isinstance(f, ProductAttribute) and f.status == "MISSING"]

    assert faltantes
    for nombre in faltantes:
        assert nombre in dna.missing_information


def test_los_estados_con_valor_declaran_confianza() -> None:
    """Sin confianza no se puede decidir si un dato es utilizable."""
    con_valor = [a for a in _atributos().values() if a.status != "MISSING"]

    assert con_valor
    for atributo in con_valor:
        assert atributo.value is not None, atributo.name
        assert atributo.confidence is not None, atributo.name


def test_la_inferencia_deja_evidencia_de_modelo() -> None:
    """El atributo INFERRED se sostiene en una evidencia MODEL_OUTPUT.

    `created_by == "model"` es hoy la única proyección del tipo: la columna
    `evidence_kind` todavía no existe (nota en `core/evidence/__init__.py`).
    """
    from database.models import EvidenceRecord

    evidencias = [f for f in _filas_del_seed() if isinstance(f, EvidenceRecord)]
    de_modelo = [
        e for e in evidencias if e.created_by == "model" and e.subject_kind == "product_attribute"
    ]

    assert len(de_modelo) == 1
    assert de_modelo[0].model_provider
    assert de_modelo[0].model_name
    # Sin prompt_version la salida es irreproducible; el builder lo exige.
    assert de_modelo[0].prompt_version
