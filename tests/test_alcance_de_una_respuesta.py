"""A cuántas fichas alcanza una respuesta de vocabulario, ANTES de guardarla.

LO QUE ESTE FICHERO PROTEGE

Que quien contesta una pregunta del motor vea a cuántas fichas se aplicará su
respuesta, contado con la MISMA regla con la que el motor la aplica.

El 6-oct César contestó sobre un cable eligiendo «acero» y se guardó «nada de
acero es galvanizado». La pantalla decía «vale para todas las fichas que digan
lo mismo» sin decir cuántas: eran 134 de 181.

`la_ficha_dice` es la mitad de la ficha de `_lo_aprendido_la_descarta`, sacada
a una función sin cambiar nada; los tests del motor siguen siendo los que
protegen el descarte. Éstos protegen que el endpoint la use y cuente bien.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

import pytest
from apps.api.routers.review import alcance_vocabulario
from core.rgi_engine import ClassificationContext, ProductFact
from core.rgi_engine.rules import la_ficha_dice
from database.models import Product, ProductAttribute, ProductDna

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _ficha(descripcion: str, **hechos: str) -> ClassificationContext:
    return ClassificationContext(
        description=descripcion,
        operation_date=date(2026, 8, 1),
        facts=tuple(ProductFact(name=k, value=v, status="OBSERVED") for k, v in hechos.items()),
    )


# ── La regla ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_todas_las_palabras_del_termino_tienen_que_estar() -> None:
    ficha = _ficha("CABLE DE ACERO GALVANIZADO", construccion="6x19")
    assert la_ficha_dice("acero galvanizado", ficha)
    assert not la_ficha_dice("acero inoxidable", ficha), "con una palabra no basta"


@pytest.mark.unit
def test_cuentan_los_valores_de_los_hechos_no_los_nombres_de_los_campos() -> None:
    ficha = _ficha("CABLE", material="acero galvanizado")
    assert la_ficha_dice("galvanizado", ficha)
    assert not la_ficha_dice("material", ficha)


@pytest.mark.unit
def test_una_notacion_se_busca_literal() -> None:
    ficha = _ficha("CABLE DE ACERO, CONSTRUCCION 6X19")
    assert la_ficha_dice("6x19", ficha)
    assert not la_ficha_dice("6x36", ficha)


# ── El endpoint, contra Postgres ────────────────────────────────────────────


def _producto(session: Session, resumen: str, **hechos: str) -> Product:
    producto = Product(
        sku=f"T-{uuid.uuid4().hex[:10]}", commercial_name=resumen, data_origin="SYNTHETIC"
    )
    session.add(producto)
    session.flush()
    dna = ProductDna(product_id=producto.id, version=1, summary=resumen, data_origin="SYNTHETIC")
    session.add(dna)
    session.flush()
    for nombre, valor in hechos.items():
        session.add(
            ProductAttribute(
                product_dna_id=dna.id,
                name=nombre,
                value=valor,
                status="OBSERVED",
                data_origin="SYNTHETIC",
            )
        )
    session.flush()
    return producto


@pytest.mark.integration
def test_cuenta_las_fichas_que_dicen_el_termino(pg_session: Session) -> None:  # noqa: F811
    """Se mide la DIFERENCIA que introducen las fichas del test: no depende de
    lo que haya en la base, y en el CI —base vacía— sigue midiendo 2."""
    termino = f"zz{uuid.uuid4().hex[:8]}"
    antes = alcance_vocabulario(pg_session, termino)

    a = _producto(pg_session, f"CABLE {termino.upper()}")
    b = _producto(pg_session, "TUBO", acabado=termino)
    _producto(pg_session, "OLLA DE ALUMINIO")

    despues = alcance_vocabulario(pg_session, termino)

    assert despues.fichas - antes.fichas == 2
    assert despues.de_un_total - antes.de_un_total == 3
    assert {a.sku, b.sku} <= {e.split(" · ")[0] for e in despues.ejemplos}


@pytest.mark.integration
def test_quita_la_etiqueta_del_campo_como_al_guardar(pg_session: Session) -> None:  # noqa: F811
    """`material = «acero»` se guarda como «acero»; el alcance, igual."""
    termino = f"zz{uuid.uuid4().hex[:8]}"
    _producto(pg_session, "CABLE", material=termino)

    alcance = alcance_vocabulario(pg_session, f"material = «{termino}»")

    assert alcance.termino_ficha == termino
    assert alcance.fichas >= 1
