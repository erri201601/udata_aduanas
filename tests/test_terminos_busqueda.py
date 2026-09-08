"""Los términos con los que se prefiltra la tarifa.

El prefiltro es un `ILIKE '%término%'` sobre la descripción de la fracción. Un
término que no aparece literal en el texto de la tarifa no filtra nada, y uno
demasiado genérico engancha media nomenclatura. Las dos fallas son silenciosas:
producen candidatos malos, y con candidatos malos la RGI 3 c) resuelve «la
última en orden numérico» sobre un conjunto que nadie eligió.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.dna import MIN_LONGITUD_TERMINO, terminos
from core.product_dna import ExtractedAttribute, ProductDnaDraft

pytestmark = pytest.mark.unit


def _dna(resumen: str, *atributos: tuple[str, str | None, str | None, str]) -> ProductDnaDraft:
    return ProductDnaDraft(
        summary=resumen,
        attributes=tuple(
            ExtractedAttribute(
                name=n,
                value=v,
                unit=u,
                status=e,  # type: ignore[arg-type]
                confidence=Decimal("0.9"),
                locator=v,
            )
            for n, v, u, e in atributos
        ),
    )


def test_el_resumen_se_parte_en_palabras() -> None:
    """Una frase completa no coincide con ninguna descripción de la tarifa."""
    t = terminos(_dna("Laptop portátil, 14 pulgadas, 8 GB RAM, peso 1.4 kg."))

    assert "Laptop" in t
    assert "portátil" in t
    assert "pulgadas" in t
    assert not any(" " in x for x in t)


def test_los_numeros_sueltos_no_son_terminos() -> None:
    """EL TEST QUE IMPORTA.

    `weight_kg = "1.4"` aportaba el término `"1.4"`, que engancha cualquier
    fracción que mencione ese número por cualquier motivo. En el pedimento de
    prueba eso llevaba a RGI 1 a devolver 25 partidas candidatas y a RGI 3 c) a
    resolver 8539 —lámparas— para una computadora portátil.
    """
    t = terminos(
        _dna(
            "Computadora",
            ("ram_gb", "8", "GB", "OBSERVED"),
            ("weight_kg", "1.4", "kg", "EXTRACTED"),
        )
    )

    assert "8" not in t
    assert "1.4" not in t
    assert "8 GB" not in t


def test_las_palabras_cortas_se_descartan() -> None:
    """«de», «con», «kg», «RAM» enganchan media tarifa."""
    t = terminos(_dna("Cable de red con RAM y kg"))

    assert all(len(x) >= MIN_LONGITUD_TERMINO for x in t)
    assert "de" not in t
    assert "RAM" not in t


def test_no_se_repiten_terminos() -> None:
    """Repetir un término no mejora el filtro y consume el cupo."""
    t = terminos(_dna("Portátil portátil PORTÁTIL"))

    assert len(t) == 1


def test_un_atributo_inferido_no_entra() -> None:
    """Buscar en la nomenclatura con un dato inferido llevaría al motor por una
    vía que nadie leyó en el documento."""
    t = terminos(
        _dna(
            "Computadora",
            ("chassis_material", "aluminio", None, "INFERRED"),
            ("housing", "policarbonato", None, "OBSERVED"),
        )
    )

    assert "aluminio" not in t
    assert "policarbonato" in t


def test_el_cupo_de_terminos_se_respeta() -> None:
    """Más términos ensanchan la consulta hasta que deja de discriminar."""
    t = terminos(_dna("alfa bravo charlie delta noviembre oscar papa quebec romeo"))

    assert len(t) <= 6
