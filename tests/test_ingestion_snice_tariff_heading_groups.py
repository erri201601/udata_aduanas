"""Tests de los niveles intermedios de un guion (ADR 0004): detección por
página (`_headings_de_pagina`) y el recorrido con estado que los asocia a
su partida y a las subpartidas que agrupan (`_recorrer_con_grupos`).

`unit`, sin red ni base de datos -- el fragmento de
`tests/fixtures/ligie_pagina_799_73_05.py` es el XML real de la página 799
de la LIGIE (partida 73.05 completa), el caso que abrió el ADR: 730512
("Los demás, soldados longitudinalmente.") y 730531 ("Soldados
longitudinalmente.") son indistinguibles sin saber de qué grupo cuelga cada
una.
"""

from __future__ import annotations

import pytest
from ingestion.snice.tariff_headings import (
    ParsedHeading,
    ParsedHeadingGroup,
    _headings_de_pagina,
    _palabras_de,
    _recorrer_con_grupos,
)

from tests.fixtures.ligie_pagina_799_73_05 import PAGINA_799_73_05

pytestmark = pytest.mark.unit


def _filas_799() -> list[tuple[str | None, int, str, bool]]:
    return _headings_de_pagina(_palabras_de(PAGINA_799_73_05))


# ── `_headings_de_pagina`: detección de guiones, por página ─────────────────


def test_detecta_los_dos_grupos_de_7305_sin_codigo() -> None:
    filas = _filas_799()
    grupos = [f for f in filas if f[1] == 0]
    assert [g[2] for g in grupos] == [
        "Tubos de los tipos utilizados en oleoductos o gasoductos:",
        "Los demás, soldados:",
    ]
    assert all(g[0] is None for g in grupos), "un grupo nunca lleva código (regla 2 CLAUDE.md)"


def test_7305_no_lleva_pegado_el_texto_del_primer_grupo() -> None:
    """Regresión del bug que abrió el ADR: antes de esto, la descripción de
    7305 terminaba en "...de hierro o acero. Tubos de los tipos utilizados
    en oleoductos o gasoductos:" -- el grupo bebía de la partida."""
    filas = _filas_799()
    (partida,) = [f for f in filas if f[1] == 4]
    assert partida[0] == "7305"
    assert partida[2] == (
        "Los demás tubos (por ejemplo: soldados o remachados) de sección "
        "circular con diámetro exterior superior a 406.4 mm, de hierro o acero."
    )
    assert "oleoductos" not in partida[2]


def test_730520_es_guion_propio_y_ninguna_otra_subpartida_lo_es() -> None:
    """7305.20 trae su PROPIO guion sencillo -- es hermana de los grupos,
    no hija de ninguno (verificado contra el PDF real: "7305.20        -")."""
    filas = _filas_799()
    por_codigo = {f[0]: f[3] for f in filas if f[1] == 6}
    assert por_codigo["730520"] is True
    assert por_codigo["730511"] is False
    assert por_codigo["730512"] is False
    assert por_codigo["730519"] is False
    assert por_codigo["730531"] is False


def test_las_subpartidas_de_seis_digitos_completas_de_la_pagina() -> None:
    filas = _filas_799()
    codigos = [f[0] for f in filas if f[1] == 6]
    assert codigos == ["730511", "730512", "730519", "730520", "730531"]


# ── `_recorrer_con_grupos`: estado (partida activa, grupo activo) ───────────


def test_recorrer_asocia_cada_subpartida_a_su_grupo_real() -> None:
    headings, grupos, asociacion = _recorrer_con_grupos(iter([_filas_799()]))

    assert asociacion["730511"] == ("7305", 1)
    assert asociacion["730512"] == ("7305", 1)
    assert asociacion["730519"] == ("7305", 1)
    assert asociacion["730531"] == ("7305", 2)
    assert "730520" not in asociacion, "hoja de un solo guion, nunca hereda el grupo activo"

    assert grupos == [
        ParsedHeadingGroup(
            parent_code="7305",
            ordinal=1,
            description="Tubos de los tipos utilizados en oleoductos o gasoductos:",
        ),
        ParsedHeadingGroup(parent_code="7305", ordinal=2, description="Los demás, soldados:"),
    ]
    assert {h.code for h in headings} == {
        "7305",
        "730511",
        "730512",
        "730519",
        "730520",
        "730531",
    }


def test_un_guion_propio_cierra_el_grupo_para_lo_que_sigue() -> None:
    """Sintético: partida -> grupo -> hoja de un solo guion -> subpartida
    normal. La última NO debe heredar el grupo de antes de la hoja."""
    pagina = [
        ("9999", 4, "Partida de prueba.", False),
        (None, 0, "Grupo uno:", False),
        ("999911", 6, "Hija del grupo uno.", False),
        ("999920", 6, "Hoja de un solo guion.", True),
        ("999921", 6, "Después de la hoja, sin grupo nuevo.", False),
    ]
    _, grupos, asociacion = _recorrer_con_grupos(iter([pagina]))

    assert asociacion == {"999911": ("9999", 1)}
    assert "999920" not in asociacion
    assert "999921" not in asociacion
    assert len(grupos) == 1


def test_un_grupo_sin_partida_activa_no_se_cuenta() -> None:
    """Sintético: un guion sin código aparece antes de cualquier partida
    (p. ej. ruido al principio del documento) -- se ignora, no truena."""
    pagina = [
        (None, 0, "Guion huérfano, sin partida antes.", False),
        ("9999", 4, "Partida de prueba.", False),
    ]
    headings, grupos, asociacion = _recorrer_con_grupos(iter([pagina]))

    assert grupos == []
    assert asociacion == {}
    assert [h.code for h in headings] == ["9999"]


def test_gana_la_primera_aparicion_de_la_partida_tambien_para_sus_grupos() -> None:
    """Sintético: la misma partida aparece dos veces (tabla real, luego un
    índice/referencia cruzada). Los grupos de la SEGUNDA aparición no se
    leen -- mismo criterio que ya usa el resto del parser para código y
    descripción."""
    pagina = [
        ("9999", 4, "Descripción real de la tabla.", False),
        (None, 0, "Grupo real:", False),
        ("999911", 6, "Hija real.", False),
        ("9999", 4, "Descripción de una referencia posterior -- no debe ganar.", False),
        (None, 0, "Grupo espurio, de la referencia:", False),
        ("999922", 6, "Otra fila, no debería asociarse al grupo espurio.", False),
    ]
    headings, grupos, asociacion = _recorrer_con_grupos(iter([pagina]))

    (partida,) = [h for h in headings if h.code == "9999"]
    assert partida.description == "Descripción real de la tabla."
    assert [g.description for g in grupos] == ["Grupo real:"]
    assert asociacion == {"999911": ("9999", 1)}
    assert "999922" not in asociacion


def test_el_estado_persiste_entre_paginas() -> None:
    """Sintético: la partida y su grupo aparecen en una página, y las
    subpartidas hijas en la siguiente -- el guion no tiene por qué compartir
    página con lo que agrupa."""
    pagina_1: list[tuple[str | None, int, str, bool]] = [
        ("9999", 4, "Partida de prueba.", False),
        (None, 0, "Grupo que sigue en la página siguiente:", False),
    ]
    pagina_2: list[tuple[str | None, int, str, bool]] = [
        ("999911", 6, "Primera hija, en otra página.", False),
        ("999912", 6, "Segunda hija.", False),
    ]
    _, grupos, asociacion = _recorrer_con_grupos(iter([pagina_1, pagina_2]))

    assert len(grupos) == 1
    assert asociacion == {"999911": ("9999", 1), "999912": ("9999", 1)}


def test_parsed_heading_group_nunca_lleva_code() -> None:
    """`ParsedHeadingGroup` no tiene campo `code` -- ni siquiera opcional.
    Comprobación de contrato, no de comportamiento: si algún día alguien le
    agrega uno, este test lo hace explícito para que sea una decisión, no un
    descuido."""
    campos = ParsedHeadingGroup.__dataclass_fields__.keys()
    assert "code" not in campos
    assert set(campos) == {"parent_code", "ordinal", "description"}


def test_parsed_heading_no_cambio_de_forma() -> None:
    """`parse_headings` (sin grupos) sigue devolviendo exactamente lo mismo
    que antes del ADR 0004 -- no se le agregó ningún campo."""
    campos = ParsedHeading.__dataclass_fields__.keys()
    assert set(campos) == {"code", "level", "chapter", "description"}
