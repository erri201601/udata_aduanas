"""El Copilot cumple el §31 (ADR 0010).

Los cinco tests que el ADR exige van primero, con su nombre. Después, los del
validador de citas y oraciones, que es lo que decide —código, no modelo— si una
redacción se entrega.

`ProveedorFalso` lo reutiliza `test_copilot_router.py`: por omisión redacta una
oración citando `[1]`, que es lo que haría un modelo obediente.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from core.copilot import (
    CITA_INEXISTENTE,
    SIN_EVIDENCIA,
    SIN_MODELO,
    PasajeParaRedactar,
    faltantes_deterministas,
    oraciones,
    redactar,
    requiere_revision,
    validar,
)
from core.llm.errors import ProviderNotConfiguredError, ProviderRateLimitError
from core.llm.types import CallMetadata, StructuredResponse

pytestmark = [pytest.mark.unit, pytest.mark.contract]

FECHA = date(2024, 3, 15)


class ProveedorFalso:
    """Un `ModelProvider` que devuelve la redacción que se le diga."""

    name = "fake"

    def __init__(
        self,
        answer: str = "El importador debe declarar el valor en aduana [1].",
        *,
        faltan: tuple[str, ...] = (),
        falla: Exception | None = None,
    ) -> None:
        self.answer = answer
        self.faltan = faltan
        self.falla = falla
        self.llamadas = 0
        self.recibido: str = ""

    def generate_structured(self, messages: Any, schema: type, **k: Any) -> Any:
        self.llamadas += 1
        self.recibido = messages[0].content
        if self.falla is not None:
            raise self.falla
        return StructuredResponse[schema](  # type: ignore[valid-type]
            data=schema(answer=self.answer, missing_information=list(self.faltan)),
            metadata=CallMetadata(
                model_provider="fake",
                model_name="fake-1",
                prompt_id=k.get("prompt_id"),
                prompt_version=k.get("prompt_version"),
            ),
        )


class ProveedorQueNoDebeLlamarse(ProveedorFalso):
    def generate_structured(self, messages: Any, schema: type, **k: Any) -> Any:
        raise AssertionError("se llamó al modelo sin pasajes que fundamenten")


def _pasajes(n: int) -> list[PasajeParaRedactar]:
    return [
        PasajeParaRedactar(n=i, cita=f"Ley Aduanera, art. {50 + i}", texto=f"Texto {i}.")
        for i in range(1, n + 1)
    ]


def _redactar(proveedor: ProveedorFalso, n: int = 3) -> Any:
    return redactar("¿qué?", fecha=FECHA, pasajes=_pasajes(n), proveedor=lambda: proveedor)


# ── Los cinco tests del ADR 0010 ────────────────────────────────────────────


def test_ninguna_cita_fuera_de_los_pasajes_recuperados() -> None:
    """Cita `[7]` con 3 pasajes entregados: se descarta la redacción ENTERA."""
    r = _redactar(ProveedorFalso("Una oración bien citada [1]. Otra inventada [7]."))

    assert r.answer == SIN_EVIDENCIA
    assert r.missing_information == (CITA_INEXISTENTE,)
    assert r.confidence == Decimal("0.00")
    assert r.citadas == ()
    assert r.redactada is False
    assert requiere_revision(r, r.missing_information) is True


def test_sin_pasajes_que_fundamenten_no_se_llama_al_modelo() -> None:
    r = redactar("¿qué?", fecha=FECHA, pasajes=[], proveedor=lambda: ProveedorQueNoDebeLlamarse())

    assert r.answer == SIN_EVIDENCIA
    assert r.confidence == Decimal("0.00")
    assert r.citadas == ()
    assert requiere_revision(r, []) is True


def test_sources_solo_contiene_lo_citado() -> None:
    """5 pasajes entregados, el texto cita `[2]`: una sola fuente."""
    r = _redactar(ProveedorFalso("Sólo el segundo responde [2]."), n=5)

    assert r.citadas == (2,)


def test_confidence_con_una_oracion_sin_cita_entre_tres() -> None:
    r = _redactar(ProveedorFalso("Primera [1]. Segunda sin cita. Tercera [2]."))

    assert r.confidence == Decimal("0.67")
    assert requiere_revision(r, r.missing_information) is True


def test_proveedor_caido_no_finge_ni_dice_sin_evidencia() -> None:
    """La evidencia existe; lo que falta es la redacción (punto 7)."""
    r = _redactar(ProveedorFalso(falla=ProviderRateLimitError("429", provider="fake")))

    assert r.answer == SIN_MODELO
    assert r.answer != SIN_EVIDENCIA
    assert r.redactada is False
    assert r.modelo_no_disponible is not None and "429" in r.modelo_no_disponible
    assert requiere_revision(r, []) is True


# ── El resto del contrato ───────────────────────────────────────────────────


def test_sin_llave_tambien_es_proveedor_caido() -> None:
    def sin_llave() -> Any:
        raise ProviderNotConfiguredError("falta ANTHROPIC_API_KEY", provider="anthropic")

    r = redactar("¿qué?", fecha=FECHA, pasajes=_pasajes(2), proveedor=sin_llave)
    assert r.answer == SIN_MODELO


def test_una_redaccion_toda_citada_y_sin_faltantes_no_pide_revision() -> None:
    """El único camino a `requires_human_review = false`."""
    r = _redactar(ProveedorFalso("Primera [1]. Segunda [2, 3]."))

    assert r.confidence == Decimal("1.00")
    assert r.citadas == (1, 2, 3)
    assert requiere_revision(r, []) is False
    assert requiere_revision(r, ["falta el PROSEC"]) is True


def test_al_modelo_le_llegan_los_pasajes_numerados() -> None:
    proveedor = ProveedorFalso()
    _redactar(proveedor, n=2)

    assert "[1] Ley Aduanera, art. 51\nTexto 1." in proveedor.recibido
    assert "[2] Ley Aduanera, art. 52" in proveedor.recibido
    assert "2024-03-15" in proveedor.recibido


def test_una_redaccion_vacia_no_se_entrega() -> None:
    r = _redactar(ProveedorFalso("   "))
    assert r.answer == SIN_EVIDENCIA
    assert r.redactada is False


def test_lo_que_falta_segun_el_modelo_se_conserva() -> None:
    r = _redactar(ProveedorFalso(faltan=("el monto del cupo",)))
    assert r.missing_information == ("el monto del cupo",)


# ── Oraciones y citas ───────────────────────────────────────────────────────


def test_una_abreviatura_no_parte_la_oracion() -> None:
    """«el art. 54 dice…» es UNA oración; partirla dejaría una sin cita."""
    assert oraciones("Según el art. 54 de la Ley, procede [1]. Y otra [2].") == [
        "Según el art. 54 de la Ley, procede [1].",
        "Y otra [2].",
    ]


def test_cada_vineta_es_una_oracion() -> None:
    assert len(oraciones("- primera [1]\n- segunda sin cita")) == 2


def test_las_citas_agrupadas_cuentan_todas() -> None:
    v = validar("Algo [1, 3]. Otra cosa [2][3].", {1, 2, 3})
    assert v.citadas == (1, 3, 2)
    assert v.con_cita == 2 and v.oraciones == 2


def test_una_cita_inexistente_se_detecta_aunque_vaya_agrupada() -> None:
    assert validar("Algo [1, 9].", {1, 2}).inexistentes == (9,)


# ── Lo que falta sin preguntarle al modelo (punto 5) ────────────────────────


def test_la_busqueda_degradada_se_declara_como_faltante() -> None:
    faltan = faltantes_deterministas(
        "valor en aduana", corpus_consultado=["Ley Aduanera"], degradado_por="sin vectores"
    )
    assert faltan == ["La búsqueda se hizo por término, no por significado: sin vectores."]


def test_un_instrumento_no_cargado_se_declara() -> None:
    """Lo que falta sale de comparar con el corpus, no de una lista de ausentes."""
    faltan = faltantes_deterministas(
        "¿aplica PROSEC a esta fracción?",
        corpus_consultado=["Ley Aduanera", "LIGIE 2022"],
        degradado_por=None,
    )
    assert len(faltan) == 1 and "PROSEC" in faltan[0]


def test_un_instrumento_cargado_no_se_declara_como_faltante() -> None:
    faltan = faltantes_deterministas(
        "¿qué dice la Ley Aduanera del valor?",
        corpus_consultado=["Ley Aduanera"],
        degradado_por=None,
    )
    assert faltan == []
