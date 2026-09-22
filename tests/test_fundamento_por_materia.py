"""Qué puede fundamentar una clasificación, y qué no (Persona 1, 22-sep-2026).

`a_legal_refs` ya filtraba por PROCEDENCIA —lo sintético no fundamenta—, pero
nadie filtraba por MATERIA. Son dos dimensiones distintas y la segunda faltaba:
el artículo 78 de la Ley Aduanera es oficial, vigente y verificable, y aun así
no sustenta dónde clasifica una mercancía.

El defecto salió en el ensayo de la demo: el expediente citaba los artículos
64, 65, 67, 71, 78, 79 y 80 —el capítulo de valor en aduana— diciendo «sustenta
la clasificación». Citas correctas de normas que no venían al caso, que ante un
agente aduanal es peor que una cita inventada, porque parece rigor.

`integration` — contra PostgreSQL real, con chunks de verdad: un doble no
probaría que los tipos de documento cargados son los que creemos.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from core.classification import fundamenta_clasificacion

from tests.test_canonical_model import pg_session  # noqa: F401 — fixture reutilizada

pytestmark = pytest.mark.unit


def test_la_nomenclatura_fundamenta() -> None:
    """La LIGIE y sus notas: el texto de partida decide la clasificación."""
    assert fundamenta_clasificacion("TARIFF")


def test_la_ley_aduanera_no_fundamenta_una_clasificacion() -> None:
    """Regula el procedimiento —valoración, despacho— no la nomenclatura."""
    assert not fundamenta_clasificacion("LAW")


def test_un_documento_sin_tipo_no_se_presume_fundamento() -> None:
    """Lo que no se puede comprobar no pasa. `None` es no, no «quizá»."""
    assert not fundamenta_clasificacion(None)


@pytest.mark.integration
def test_el_filtro_deja_fuera_la_ley_aduanera_y_conserva_la_ligie(
    pg_session: sa.orm.Session,  # noqa: F811
) -> None:
    """De punta a punta, con chunks reales de la base compartida."""
    from apps.api.clasificacion import _solo_lo_que_funda_una_clasificacion
    from database.repositories.chunks import PostgresChunkStore
    from rag.retrieval import Recuperacion

    store = PostgresChunkStore(pg_session)
    from datetime import date

    todos = store.search(on_date=date(2026, 9, 22), limit=400)
    ley = [c for c in todos if "Aduanera" in (c.document or "")]
    ligie = [c for c in todos if "Importación" in (c.document or "")]
    if not ley or not ligie:
        pytest.skip("la base no tiene cargados los dos instrumentos")

    antes = Recuperacion(chunks=(ley[0], ligie[0]), on_date=date(2026, 9, 22))
    despues = _solo_lo_que_funda_una_clasificacion(pg_session, antes)

    documentos = {c.document for c in despues.chunks}
    assert ligie[0].document in documentos
    assert ley[0].document not in documentos
