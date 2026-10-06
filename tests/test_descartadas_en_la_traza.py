"""Lo que el motor tiene por imposible, como dato y no sólo como frase.

LO QUE ESTE FICHERO PROTEGE

Que cada descarte del motor —nota legal, materia, contradicción con la ficha o
respuesta firmada— quede en `RGIResult.descartadas` con su código, su motivo y
de dónde sale, y que llegue así a la traza que se congela en la base.

Hasta ahora sólo existía dentro de `reasoning_summary`, que es texto para
personas. El 6-oct un clasificador tecleó 73121008 como «fracción correcta»
mientras su propia nota explicaba que era incompatible; la decisión vigente ya
la había descartado con ese motivo, y ninguna pantalla podía leerlo para
avisarle. Este campo es lo que el aviso necesita.

Y dos propiedades sin las que el aviso haría daño:

- la fracción que el motor ELIGE nunca aparece como descartada;
- las candidatas de una abstención NO son descartes. Si el motor no eligió
  entre tres viables, avisar sobre ellas saltaría en cada veredicto.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from core.classification.result import ClassificationOutcome
from core.rgi_engine import RGIStatus, TariffCandidate, classify
from core.rgi_engine.results import ClassificationTrace, Descarte
from database.repositories.classification import _traza

from tests.test_rgi_engine import (
    _HERMANAS_7324,
    FRAC_CABLE,
    PARTIDA_7312,
    PARTIDAS_TUBERIA,
    SUB_731210,
    CatalogoFalso,
    NotasFalsas,
    _catalogo_7615,
    _contexto_cable,
    _contexto_fregadero,
    _contexto_tuberia,
    _olla_de_aluminio,
    catalogo_completo,
    contexto,
)

pytestmark = pytest.mark.unit


def _por_codigo(descartadas: tuple[Descarte, ...]) -> dict[str, Descarte]:
    return {d.code: d for d in descartadas}


# ── Uno por cada origen ─────────────────────────────────────────────────────


def test_una_nota_legal_queda_como_descarte_de_partida() -> None:
    nota = "Este capítulo no comprende las máquinas de la partida 84.70."
    traza = classify(contexto(), catalog=catalogo_completo(), notes=NotasFalsas({"8471": nota}))

    d = _por_codigo(traza.steps[0].descartadas)["8471"]
    assert d.por == "NOTA_LEGAL"
    assert d.motivo == nota


def test_la_materia_descarta_una_partida_y_lo_dice() -> None:
    traza = classify(
        _contexto_tuberia(), catalog=CatalogoFalso(PARTIDAS_TUBERIA, [], []), notes=NotasFalsas()
    )

    d = _por_codigo(traza.steps[0].descartadas)["3926"]
    assert d.por == "MATERIA"
    assert "plastico" in d.motivo


def test_la_materia_que_opone_una_hermana_descarta_una_subpartida() -> None:
    """El fregadero de inoxidable no puede ser la bañera de fundición."""
    partida = TariffCandidate(
        code="7324",
        text="Artículos de higiene o tocador, y sus partes, de fundición, hierro o acero.",
        level="HEADING",
        specificity=2,
    )
    traza = classify(
        _contexto_fregadero(),
        catalog=CatalogoFalso([partida], _HERMANAS_7324, []),
        notes=NotasFalsas(),
    )

    d = _por_codigo(traza.steps[-1].descartadas)["732421"]
    assert d.por == "MATERIA"
    assert "fundicion" in d.motivo


def test_una_contradiccion_con_la_ficha_descarta_una_fraccion() -> None:
    """«Sin galvanizar» no puede ser un cable que consta galvanizado."""
    traza = classify(
        _contexto_cable(),
        catalog=CatalogoFalso([PARTIDA_7312], [SUB_731210], FRAC_CABLE),
        notes=NotasFalsas(),
    )

    d = _por_codigo(traza.steps[-1].descartadas)["73121008"]
    assert d.por == "CONTRADICCION"
    assert "galvanizar" in d.motivo


def test_una_respuesta_firmada_se_distingue_del_texto_legal() -> None:
    """Quien audite tiene que ver que esto se apoya en una persona.

    Con el cable 6x19 y la respuesta «"6x19" no es "constituidos por 7
    alambres"», la 73121008 sigue cayendo por el texto («sin galvanizar») y
    la 73121007 cae por la respuesta. Las dos razones conviven en el mismo
    paso, y cada una dice de dónde sale.
    """
    traza = classify(
        _contexto_cable(exclusiones=(("6x19", "constituidos por 7 alambres"),)),
        catalog=CatalogoFalso([PARTIDA_7312], [SUB_731210], FRAC_CABLE),
        notes=NotasFalsas(),
    )

    descartes = _por_codigo(traza.steps[-1].descartadas)
    assert descartes["73121008"].por == "CONTRADICCION"
    assert descartes["73121007"].por == "RESPUESTA_FIRMADA"
    assert "6x19" in descartes["73121007"].motivo


def test_una_respuesta_firmada_descarta_una_subpartida_aunque_no_resuelva() -> None:
    traza = classify(
        _olla_de_aluminio((("domestico/cocina", "Artículos de higiene o tocador"),)),
        catalog=_catalogo_7615(),
        notes=NotasFalsas(),
    )

    assert _por_codigo(traza.steps[-1].descartadas)["761520"].por == "RESPUESTA_FIRMADA"


# ── Las dos propiedades que hacen útil el aviso ─────────────────────────────


def test_las_candidatas_de_una_abstencion_no_son_descartes() -> None:
    """EL MOTOR NO ELIGIÓ, ASÍ QUE NO DESCARTÓ.

    El cable 6x19 galvanizado empata y el motor se niega. Lo que sigue vivo es
    trabajo para el clasificador: elegir una de ellas es justo lo que se le
    pide, y avisarle de que «el motor no la eligió» sería ruido en cada
    veredicto.
    """
    traza = classify(
        _contexto_cable(),
        catalog=CatalogoFalso([PARTIDA_7312], [SUB_731210], FRAC_CABLE),
        notes=NotasFalsas(),
    )
    ultimo = traza.steps[-1]

    assert traza.final_status is RGIStatus.HUMAN_REVIEW_REQUIRED
    vivas = {c.code for c in ultimo.candidate_codes}
    assert vivas, "el caso tiene que quedar con candidatas para que el test signifique algo"
    assert vivas.isdisjoint(d.code for d in ultimo.descartadas)


def test_la_fraccion_elegida_nunca_aparece_como_descartada() -> None:
    """Cuando descartar deja una, se elige ésa; y ésa no puede estar descartada."""
    cat = CatalogoFalso(
        [PARTIDA_7312],
        [SUB_731210],
        [
            TariffCandidate(
                code="73121001",
                text="Galvanizados, con diámetro mayor de 4 mm.",
                level="FRACTION",
                specificity=1,
            ),
            TariffCandidate(
                code="73121008",
                text="Sin galvanizar, de diámetro menor o igual a 19 mm.",
                level="FRACTION",
                specificity=1,
            ),
        ],
    )
    traza = classify(_contexto_cable(), catalog=cat, notes=NotasFalsas())

    assert traza.resolved_code == "73121001"
    todas = {d.code for paso in traza.steps for d in paso.descartadas}
    assert "73121008" in todas
    assert not any(traza.resolved_code.startswith(c) for c in todas)


# ── Hasta la base ───────────────────────────────────────────────────────────


def test_la_traza_que_se_congela_lleva_los_descartes() -> None:
    """Si no llega a `rgi_trace`, la pantalla no tiene de dónde leerlo."""
    traza = classify(
        _contexto_cable(),
        catalog=CatalogoFalso([PARTIDA_7312], [SUB_731210], FRAC_CABLE),
        notes=NotasFalsas(),
    )
    congelada = _traza(
        ClassificationOutcome(
            trace=ClassificationTrace(steps=traza.steps), operation_date=date(2026, 3, 15)
        )
    )

    ultimo = congelada[-1]["descartadas"]
    assert {"code": "73121008", "motivo": ultimo[0]["motivo"], "por": "CONTRADICCION"} in ultimo
    json.dumps(congelada)  # JSONB: tiene que serializar sin conversores
