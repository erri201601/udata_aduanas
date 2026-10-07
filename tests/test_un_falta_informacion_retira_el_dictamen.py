"""Un `FALTA_INFORMACION` posterior retira el dictamen anterior de esa ficha.

LO QUE ESTE FICHERO PROTEGE

Que las mediciones lean el ÚLTIMO veredicto humano de una ficha, llegue o no a
una fracción. Las dos filtraban `fraction_code IS NOT NULL` antes de elegir el
más reciente, y con eso un `FALTA_INFORMACION` no existía para ellas: lo
saltaban y volvían al dictamen anterior.

El caso real: el 5-oct el clasificador dictaminó `73121099` para el cable
PED_SIM_010-005; el 6-oct escribió «no tengo fundamento suficiente para elegir
73121005 ni 73121099. Solicito confirmar el recubrimiento». La medición de
clasificación seguía usando `73121099` como verdad, una fracción que su autor
había retirado.

Los de integración corren contra el Postgres local dentro de una transacción
que se revierte, y se saltan sin él (en el CI no hay `.env`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from apps.evaluacion.clasificacion_39 import _CON_FRACCION_FIABLE, informe, medir
from apps.evaluacion.deteccion_26 import (
    DETECTOR_DE_FRACCION,
    _fracciones_que_un_dictamen_contradice,
)
from database.models import ClassificationDecision, PedimentoItem, ProductDna
from sqlalchemy.orm import Session

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

HACE_UN_DIA = datetime.now(UTC) - timedelta(days=1)
HOY = datetime.now(UTC)


# ── Unit: qué hace la medición con una ficha sin fundamento ─────────────────


def _fila(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "sku": "PED_SIM_010-005",
        "declarada": "73121099",
        "propuesta": "73121099",
        "dictamen": None,
        "sin_fundamento": False,
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


@pytest.mark.unit
def test_una_ficha_sin_fundamento_no_se_mide_contra_la_declaracion() -> None:
    """Medirla contra la declaración contradiría al clasificador.

    Él acaba de decir que con esa ficha no puede elegir entre la declarada y
    otra. Si el motor propusiera la declarada, contarlo como acierto sería
    darle la razón a un dato sintético contra el único experto del sistema.
    """
    r = medir(SesionDeFilas([_fila(sin_fundamento=True)]))  # type: ignore[arg-type]

    assert r.sin_fundamento == 1
    assert r.medibles == 0
    assert r.acerto == 0 and r.contra_declaracion == 0


@pytest.mark.unit
def test_el_informe_dice_cuantas_quedaron_sin_fundamento() -> None:
    r = medir(SesionDeFilas([_fila(sin_fundamento=True), _fila(sku="otra")]))  # type: ignore[arg-type]

    assert "sin fundamento: 1" in informe(r)


# ── Integración: las consultas eligen el ÚLTIMO veredicto ───────────────────


def _un_caso_sin_veredictos(session: Session) -> PedimentoItem:
    """Una partida medible cuya ficha vigente nadie ha dictaminado todavía."""
    item_id = session.execute(
        sa.text(
            """
            SELECT i.id
            FROM operational.pedimento_items i
            JOIN intelligence.product_dnas f
              ON f.product_id = i.product_id AND f.is_current
            WHERE i.declared_fraction_code IS NOT NULL
              AND EXISTS (SELECT 1 FROM intelligence.classification_decisions d
                          WHERE d.product_id = i.product_id
                            AND d.product_dna_id = f.id
                            AND d.data_origin <> 'HUMAN_VALIDATED')
              AND NOT EXISTS (SELECT 1 FROM intelligence.classification_decisions h
                              WHERE h.product_dna_id = f.id
                                AND h.data_origin = 'HUMAN_VALIDATED')
              AND NOT EXISTS (SELECT 1 FROM intelligence.ground_truth_records g
                              WHERE g.pedimento_item_id = i.id
                                AND g.error_type IN ('WRONG_FRACTION', 'WRONG_NICO'))
              AND (SELECT count(*) FROM operational.pedimento_items o
                   WHERE o.product_id = i.product_id) = 1
            LIMIT 1
            """
        )
    ).scalar()
    if item_id is None:
        pytest.skip("no hay en la base local una partida medible sin dictaminar")
    item = session.get(PedimentoItem, item_id)
    assert item is not None
    return item


def _veredicto(
    session: Session, item: PedimentoItem, fraccion: str | None, cuando: datetime
) -> None:
    """Un veredicto, sobre su propia decisión de máquina.

    Así es en la realidad y así lo exige la base: todo veredicto dice qué
    decisión revisa (CHECK) y no hay dos sobre la misma (UNIQUE).
    """
    ficha = session.scalars(
        sa.select(ProductDna).where(
            ProductDna.product_id == item.product_id, ProductDna.is_current.is_(True)
        )
    ).one()
    origen_de_la_maquina = session.scalars(
        sa.select(ClassificationDecision.data_origin).where(
            ClassificationDecision.product_id == item.product_id,
            ClassificationDecision.data_origin != "HUMAN_VALIDATED",
        )
    ).first()
    comun: dict[str, Any] = {
        "product_id": item.product_id,
        "product_dna_id": ficha.id,
        "trade_flow": "IMPORT",
        "operation_date": cuando.date(),
    }
    revisada = ClassificationDecision(
        id=uuid.uuid4(),
        **comun,
        status="HUMAN_REVIEW_REQUIRED",
        reasoning="decisión de prueba",
        data_origin=origen_de_la_maquina,
        requires_human_review=True,
        created_at=cuando - timedelta(minutes=1),
    )
    session.add(revisada)
    session.flush()
    session.add(
        ClassificationDecision(
            id=uuid.uuid4(),
            **comun,
            reviews_decision_id=revisada.id,
            status="RESOLVED" if fraccion else "INSUFFICIENT_INFORMATION",
            fraction_code=fraccion,
            reasoning="veredicto de prueba",
            data_origin="HUMAN_VALIDATED",
            requires_human_review=False,
            created_at=cuando,
        )
    )
    session.flush()


def _fila_de(session: Session, item: PedimentoItem) -> Any:
    sku = session.execute(
        sa.text("SELECT sku FROM operational.products WHERE id = :p"), {"p": item.product_id}
    ).scalar_one()
    filas = [f for f in session.execute(_CON_FRACCION_FIABLE).all() if f.sku == sku]
    assert len(filas) == 1
    return filas[0]


@pytest.mark.integration
def test_un_falta_informacion_posterior_retira_el_dictamen(pg_session: Session) -> None:  # noqa: F811
    """La que importa: es lo que pasó con PED_SIM_010-005."""
    item = _un_caso_sin_veredictos(pg_session)
    _veredicto(pg_session, item, item.declared_fraction_code, HACE_UN_DIA)
    assert _fila_de(pg_session, item).dictamen == item.declared_fraction_code

    _veredicto(pg_session, item, None, HOY)

    fila = _fila_de(pg_session, item)
    assert fila.sin_fundamento is True
    assert fila.dictamen is None, "sigue usando como verdad una fracción retirada"


@pytest.mark.integration
def test_un_dictamen_posterior_a_un_falta_informacion_vuelve_a_mandar(
    pg_session: Session,  # noqa: F811
) -> None:
    """El dato llegó y el clasificador dictaminó: la ficha vuelve a medirse."""
    item = _un_caso_sin_veredictos(pg_session)
    _veredicto(pg_session, item, None, HACE_UN_DIA)
    _veredicto(pg_session, item, "73121005", HOY)

    fila = _fila_de(pg_session, item)
    assert fila.sin_fundamento is False
    assert fila.dictamen == "73121005"


@pytest.mark.integration
def test_la_deteccion_tampoco_se_apoya_en_un_dictamen_retirado(
    pg_session: Session,  # noqa: F811
) -> None:
    """Si nadie respalda ya que la declaración esté mal, el hallazgo cuenta."""
    item = _un_caso_sin_veredictos(pg_session)
    partidas = {item.id: item}
    _veredicto(pg_session, item, "00000000", HACE_UN_DIA)
    contradichas = _fracciones_que_un_dictamen_contradice(pg_session, partidas, set())
    assert (str(item.id), DETECTOR_DE_FRACCION) in contradichas

    _veredicto(pg_session, item, None, HOY)

    assert _fracciones_que_un_dictamen_contradice(pg_session, partidas, set()) == set()


@pytest.mark.integration
def test_un_nico_que_el_dictamen_contradice_tampoco_es_falso_positivo(
    pg_session: Session,  # noqa: F811
) -> None:
    """Misma fracción, otro NICO firmado: es cierto, y el corpus no lo sembró.

    Desde que el Espejo espera el dictamen, nueve tuberías HFW con NICO 01
    declarado y 02 dictaminado salían como falsos positivos (7-oct).
    """
    from apps.evaluacion.deteccion_26 import DETECTOR_DE_NICO

    item = _un_caso_sin_veredictos(pg_session)
    if not item.declared_nico_code:
        pytest.skip("la partida elegida no declara NICO")
    _veredicto(pg_session, item, item.declared_fraction_code, HOY)
    ultimo = pg_session.scalars(
        sa.select(ClassificationDecision)
        .where(
            ClassificationDecision.product_id == item.product_id,
            ClassificationDecision.data_origin == "HUMAN_VALIDATED",
        )
        .order_by(ClassificationDecision.created_at.desc())
    ).first()
    assert ultimo is not None
    ultimo.nico_code = "98" if item.declared_nico_code != "98" else "97"
    pg_session.flush()
    partidas = {item.id: item}

    assert (str(item.id), DETECTOR_DE_NICO) in _fracciones_que_un_dictamen_contradice(
        pg_session, partidas, set(), set()
    )
    # Si el corpus sembró ese NICO, el hallazgo es un acierto, no un «cierto».
    assert (str(item.id), DETECTOR_DE_NICO) not in _fracciones_que_un_dictamen_contradice(
        pg_session, partidas, set(), {item.id}
    )
