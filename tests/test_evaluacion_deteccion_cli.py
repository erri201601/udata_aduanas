"""Tests de la línea de comandos de la métrica del §26.

Lo que se prueba aquí no es el formato: es que elegir mal el escenario no pase
inadvertido. Medir el sembrado creyendo medir el corpus ya produjo un falso
positivo inexistente, y el remedio fue que la herramienta diga qué corpus hay
y qué corpus midió.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from apps.evaluacion.deteccion_26 import Corpus, _resolver, _tabla

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.unit

CORPUS = Corpus(
    id=uuid.UUID("3b38c4aa-abea-4e8a-aaaa-ba8cd8b22081"),
    slug="corpus-espejo",
    nombre="15 pedimentos con anomalías sembradas",
    pedimentos=15,
    eventos=60,
)
SEMBRADO = Corpus(
    id=uuid.UUID("fef54668-0000-4000-8000-000000000000"),
    slug="semilla",
    nombre="Datos de arranque",
    pedimentos=1,
    eventos=1,
)


@pytest.fixture
def _catalogo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.evaluacion.deteccion_26.corpus_disponibles",
        lambda _sesion: [CORPUS, SEMBRADO],
    )


def _sesion() -> Session:
    return object()  # type: ignore[return-value]


@pytest.mark.usefixtures("_catalogo")
def test_el_slug_evita_tener_que_teclear_el_uuid() -> None:
    assert _resolver(_sesion(), "corpus-espejo") == CORPUS


@pytest.mark.usefixtures("_catalogo")
def test_el_uuid_sigue_sirviendo() -> None:
    assert _resolver(_sesion(), str(CORPUS.id)) == CORPUS


@pytest.mark.usefixtures("_catalogo")
def test_un_uuid_que_no_existe_no_se_mide_en_silencio() -> None:
    """Sin esto, un id equivocado mediría toda la base y nadie lo notaría."""
    with pytest.raises(SystemExit) as error:
        _resolver(_sesion(), str(uuid.uuid4()))

    assert "corpus-espejo" in str(error.value)


@pytest.mark.usefixtures("_catalogo")
def test_un_slug_desconocido_dice_cuales_hay() -> None:
    with pytest.raises(SystemExit) as error:
        _resolver(_sesion(), "corpus-que-no-existe")

    mensaje = str(error.value)
    assert "corpus-espejo" in mensaje
    assert "semilla" in mensaje


def test_la_tabla_muestra_el_tamano_de_cada_corpus() -> None:
    """El sembrado y el corpus se distinguen por el tamaño, no por el id."""
    tabla = _tabla([CORPUS, SEMBRADO])

    assert "corpus-espejo" in tabla
    assert "15" in tabla
    assert "60" in tabla
    assert "semilla" in tabla
