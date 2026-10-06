"""Retirar una respuesta de vocabulario que resultó equivocada.

LO QUE ESTE FICHERO PROTEGE

Que una respuesta retirada deje de aplicarse para TODAS las fechas de
operación, también las anteriores al día en que se retira. La vigencia del
vocabulario sigue a la del texto de la tarifa —desde 2022— y el corpus va de
marzo a agosto de 2026: cerrarla con fecha de hoy la dejaría actuando sobre
todo él. Parecería cerrada y seguiría citando a quien la firmó.

El caso real: César contestó eligiendo «acero», el sistema guardó «nada de
acero es galvanizado», y él pidió cerrarla como respuesta incorrecta de
alcance, no borrarla (6-oct).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from apps.api.clasificacion import _exclusiones
from apps.api.db import get_session
from apps.api.main import create_app
from apps.api.routers.review import RetiroVocabulario, retirar_vocabulario
from database.models import NomenclatureSynonym
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

DESDE_LA_TARIFA = date(2022, 6, 7)
OPERACIONES = (date(2022, 6, 7), date(2026, 3, 15), date(2026, 8, 31), date(2026, 10, 6))


def _respuesta(session: Session) -> NomenclatureSynonym:
    fila = NomenclatureSynonym(
        commercial_term=f"prueba-retiro-{uuid.uuid4().hex[:8]}",
        nomenclature_term="galvanizados",
        kind="EXCLUYE",
        note="la ficha no es eso",
        answered_by="César",
        data_origin="HUMAN_VALIDATED",
        valid_from=DESDE_LA_TARIFA,
        source_url="respuesta de César",
        source_document="Pregunta de desempate del RGI Engine",
        content_hash=f"vocab:prueba:{uuid.uuid4().hex}",
        retrieved_at=datetime.now(UTC),
    )
    session.add(fila)
    session.flush()
    return fila


def _aplica(session: Session, fila: NomenclatureSynonym, fecha: date) -> bool:
    return (fila.commercial_term, fila.nomenclature_term) in _exclusiones(session, on_date=fecha)


@pytest.mark.integration
def test_una_respuesta_retirada_no_rige_para_ninguna_fecha(pg_session: Session) -> None:  # noqa: F811
    """La que importa. Incluye fechas ANTERIORES al día del retiro."""
    fila = _respuesta(pg_session)
    assert all(_aplica(pg_session, fila, f) for f in OPERACIONES), "antes de retirarla, rige"

    retirar_vocabulario(
        fila.id,
        RetiroVocabulario(reviewer="César", motivo="«acero» no demuestra que no sea galvanizado"),
        pg_session,
    )

    for fecha in OPERACIONES:
        assert not _aplica(pg_session, fila, fecha), f"sigue rigiendo para {fecha}"


@pytest.mark.integration
def test_retirarla_no_la_borra_y_deja_el_motivo(pg_session: Session) -> None:  # noqa: F811
    """«Debe cerrarse como una respuesta incorrecta de alcance, no borrarse»."""
    fila = _respuesta(pg_session)

    retirar_vocabulario(
        fila.id,
        RetiroVocabulario(reviewer="César", motivo="incorrecta de alcance"),
        pg_session,
    )

    guardada = pg_session.get(NomenclatureSynonym, fila.id)
    assert guardada is not None
    assert guardada.data_origin == "HUMAN_VALIDATED"
    assert guardada.answered_by == "César"
    assert "la ficha no es eso" in (guardada.note or ""), "la nota original se conserva"
    assert "RETIRADA" in (guardada.note or "")
    assert "incorrecta de alcance" in (guardada.note or "")
    assert guardada.valid_to is not None and guardada.valid_to < guardada.valid_from


@pytest.mark.integration
def test_no_se_retira_dos_veces(pg_session: Session) -> None:  # noqa: F811
    fila = _respuesta(pg_session)
    peticion = RetiroVocabulario(reviewer="César", motivo="incorrecta de alcance")
    retirar_vocabulario(fila.id, peticion, pg_session)

    with pytest.raises(HTTPException) as e:
        retirar_vocabulario(fila.id, peticion, pg_session)
    assert e.value.status_code == 409


@pytest.mark.unit
def test_una_respuesta_que_no_existe_da_404() -> None:
    class SesionVacia:
        def get(self, *_a: Any, **_k: Any) -> None:
            return None

    app = create_app()
    app.dependency_overrides[get_session] = SesionVacia
    with TestClient(app) as c:
        r = c.post(
            f"/review/vocabulario/{uuid.uuid4()}/retirar",
            json={"reviewer": "César", "motivo": "no existe"},
        )
    assert r.status_code == 404


@pytest.mark.unit
def test_retirar_exige_quien_y_por_que() -> None:
    """Una retirada sin motivo deja una fila que nadie sabrá explicar."""
    app = create_app()
    with TestClient(app) as c:
        sin_motivo = c.post(
            f"/review/vocabulario/{uuid.uuid4()}/retirar", json={"reviewer": "César"}
        )
        sin_quien = c.post(
            f"/review/vocabulario/{uuid.uuid4()}/retirar", json={"motivo": "porque sí"}
        )
    assert sin_motivo.status_code == 422
    assert sin_quien.status_code == 422
