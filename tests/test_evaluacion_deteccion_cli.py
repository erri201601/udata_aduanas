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
    slug="corpus_espejo_v1",
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
    assert _resolver(_sesion(), "corpus_espejo_v1") == CORPUS


@pytest.mark.usefixtures("_catalogo")
def test_el_uuid_sigue_sirviendo() -> None:
    assert _resolver(_sesion(), str(CORPUS.id)) == CORPUS


@pytest.mark.usefixtures("_catalogo")
def test_un_uuid_que_no_existe_no_se_mide_en_silencio() -> None:
    """Sin esto, un id equivocado mediría toda la base y nadie lo notaría."""
    with pytest.raises(SystemExit) as error:
        _resolver(_sesion(), str(uuid.uuid4()))

    assert "corpus_espejo_v1" in str(error.value)


@pytest.mark.usefixtures("_catalogo")
def test_un_slug_desconocido_dice_cuales_hay() -> None:
    with pytest.raises(SystemExit) as error:
        _resolver(_sesion(), "corpus-que-no-existe")

    mensaje = str(error.value)
    assert "corpus_espejo_v1" in mensaje
    assert "semilla" in mensaje


def test_la_tabla_muestra_el_tamano_de_cada_corpus() -> None:
    """El sembrado y el corpus se distinguen por el tamaño, no por el id."""
    tabla = _tabla([CORPUS, SEMBRADO])

    assert "corpus_espejo_v1" in tabla
    assert "15" in tabla
    assert "60" in tabla
    assert "semilla" in tabla


def test_el_ejemplo_de_la_documentacion_usa_un_slug_que_existe() -> None:
    """El ejemplo del docstring salió inventado y nadie lo habría notado.

    Un ejemplo con un slug que no existe manda a quien lo copia contra un
    error, y el CLI se estrena fallando. El slug real lo decide el cargador:
    si allí cambia, este test obliga a cambiar el ejemplo.
    """
    import apps.evaluacion.deteccion_26 as metrica
    from ingestion.sintetico.load import SCENARIO_SLUG

    assert metrica.__doc__ is not None
    assert SCENARIO_SLUG in metrica.__doc__


def test_un_producto_en_varias_partidas_no_pierde_la_exclusion() -> None:
    """Si dos partidas comparten ficha, las DOS quedan excluidas, no la última.

    Colapsarlas en un dict dejaba fuera a todas menos una, y esas volvían a
    contarse como falsos positivos por un hallazgo cierto. El corpus hoy da un
    Product por partida, pero compartirlos ya se coló una vez (PR #101,
    revertido en #103): la métrica no debería depender de que no se repita.
    """
    from types import SimpleNamespace

    from apps.evaluacion.deteccion_26 import _fichas_recortadas_a_proposito

    producto = uuid.uuid4()
    una, otra = uuid.uuid4(), uuid.uuid4()
    partidas = {
        una: SimpleNamespace(product_id=producto),
        otra: SimpleNamespace(product_id=producto),
    }
    sesion = SimpleNamespace(execute=lambda _c: [SimpleNamespace(product_id=producto)])

    excluidos = _fichas_recortadas_a_proposito(sesion, partidas, set())  # type: ignore[arg-type]

    assert {p for p, _ in excluidos} == {str(una), str(otra)}


def test_un_arbol_sucio_se_declara_en_el_reporte() -> None:
    """Un número medido con cambios sin commitear no lo puede reproducir nadie.

    Es el caso peligroso, no el raro: se mide justo mientras se trabaja. Si el
    reporte no lo dice, ese número parece salir de una revisión que no lo
    produce.
    """
    from apps.evaluacion.deteccion_26 import Procedencia, linea_de_procedencia

    linea = linea_de_procedencia(
        Procedencia(momento="2026-09-22 20:00 UTC", revision="a6e2f9f", rama="develop", sucio=True)
    )

    assert "SIN COMMITEAR" in linea
    assert "a6e2f9f" in linea


def test_un_arbol_limpio_no_lleva_advertencia() -> None:
    from apps.evaluacion.deteccion_26 import Procedencia, linea_de_procedencia

    linea = linea_de_procedencia(
        Procedencia(momento="2026-09-22 20:00 UTC", revision="a6e2f9f", rama="develop", sucio=False)
    )

    assert "SIN COMMITEAR" not in linea
    assert "2026-09-22 20:00 UTC" in linea
    assert "develop" in linea


def test_sin_git_la_medicion_no_se_rompe() -> None:
    """La métrica mide, no depende de estar en un repositorio."""
    from apps.evaluacion import deteccion_26

    original = deteccion_26._git
    try:
        deteccion_26._git = lambda *_a: ""  # type: ignore[assignment]
        p = deteccion_26.procedencia()
    finally:
        deteccion_26._git = original  # type: ignore[assignment]

    assert p.revision == "desconocida"
    assert p.sucio is False


def test_la_metrica_solo_mira_la_revision_vigente() -> None:
    """Sin esto se mide la UNIÓN de todas las auditorías, no el motor de hoy.

    Un tipo que una corrida vieja emitió y la actual ya no seguiría contando
    como acierto. La deduplicación del #112 no alcanza: colapsa copias del
    mismo par (partida, tipo), no distingue de qué corrida salió cada una.

    CI no tiene Postgres, así que aquí se comprueba que la consulta lleve el
    acotamiento. Que el acotamiento haga lo que dice está medido contra la
    base compartida: 302 hallazgos del corpus en todas las revisiones, 86 en
    la vigente.
    """
    from apps.evaluacion.deteccion_26 import consulta_de_hallazgos

    sql = str(consulta_de_hallazgos().compile(compile_kwargs={"literal_binds": True}))

    assert "shadow_reviews" in sql, "la consulta no correlaciona con las revisiones"
    assert "shadow_review_id IS NULL" in sql, "los hallazgos sin revisión se perderían"
    assert "ORDER BY" in sql and "created_at DESC" in sql, "no toma la MÁS RECIENTE"
