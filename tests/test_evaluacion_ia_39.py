"""Evaluación de IA del §39: Product DNA y búsqueda jurídica."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from apps.evaluacion.fichas_de_referencia import FICHAS
from core.evaluation.busqueda_juridica import (
    PreguntaEtiquetada,
    es_el_esperado,
    evaluar,
)
from core.evaluation.busqueda_juridica import (
    Reporte as ReporteJuridico,
)
from core.evaluation.product_dna import FichaDeReferencia, Medida, Reporte, coincide, comparar
from core.product_dna.attributes import CATALOG
from core.product_dna.types import ExtractedAttribute, ProductDnaDraft

pytestmark = pytest.mark.unit


# ── Product DNA ─────────────────────────────────────────────────────────────


def test_coincide_por_palabras_enteras() -> None:
    assert coincide("acero galvanizado", "Acero galvanizado, construcción 6x36")
    assert coincide("México", "mexico")
    assert coincide("10", "10 mm")
    assert not coincide("10", "100 mm"), "«10» no está dentro de «100»"
    assert not coincide("acero galvanizado", "acero"), "a medias no es un acierto"
    assert not coincide("acero", None)


def test_las_fichas_de_referencia_tienen_respuesta_conocida_por_construccion() -> None:
    """Cada valor esperado está escrito en el texto, y todo es del catálogo §16."""
    for ficha in FICHAS:
        for nombre, valor in ficha.esperado.items():
            assert nombre in CATALOG, f"{ficha.id}: {nombre} no es del §16"
            assert coincide(valor, ficha.texto), f"{ficha.id}: {valor!r} no está en el texto"
        assert set(ficha.ausentes) <= set(CATALOG)
        assert not set(ficha.ausentes) & set(ficha.esperado), f"{ficha.id}: dice y no dice"
        assert ficha.data_origin == "SYNTHETIC"


FICHA = FichaDeReferencia(
    id="prueba",
    texto="Cable de acero galvanizado, 10 mm.",
    esperado={"materials": "acero galvanizado", "dimensions": "10"},
    ausentes=("voltage", "power"),
)


def _a(nombre: str, valor: str | None, status: str, locator: str | None = None) -> Any:
    return ExtractedAttribute(
        name=nombre,
        value=valor,
        status=status,  # type: ignore[arg-type]
        confidence=Decimal("0.5") if status == "INFERRED" else None,
        locator=locator,
    )


def test_una_extraccion_perfecta() -> None:
    r = comparar(
        FICHA,
        ProductDnaDraft(
            attributes=(
                _a("materials", "acero galvanizado", "OBSERVED", "línea 1"),
                _a("dimensions", "10 mm", "EXTRACTED", "línea 1"),
                _a("voltage", None, "MISSING"),
                _a("power", None, "MISSING"),
            )
        ),
    )
    reporte = Reporte(fichas=(r,))

    assert reporte.precision_por_campo.porcentaje == Decimal("100.00")
    assert reporte.alucinacion.exitos == 0
    assert reporte.cobertura_de_evidencia.porcentaje == Decimal("100.00")
    assert reporte.deteccion_de_faltantes.porcentaje == Decimal("100.00")
    assert r.fallos == ()


def test_afirmar_lo_que_la_ficha_no_dice_es_alucinar() -> None:
    r = comparar(
        FICHA,
        ProductDnaDraft(
            attributes=(
                _a("materials", "acero galvanizado", "OBSERVED", "línea 1"),
                _a("voltage", "220", "EXTRACTED", "línea 1"),
                _a("power", "100", "INFERRED"),
            )
        ),
    )

    assert r.alucinados == 2
    assert r.alucinados_como_inferencia == 1, "la INFERRED al menos no se presentó como hecho"
    assert r.ausencias_detectadas == 0
    assert any("voltage" in f for f in r.fallos)


def test_un_valor_equivocado_es_error_de_extraccion_no_alucinacion() -> None:
    r = comparar(FICHA, ProductDnaDraft(attributes=(_a("materials", "aluminio", "OBSERVED", "x"),)))

    assert r.aciertos == 0 and r.esperados == 2
    assert r.alucinados == 0


def test_sin_localizador_baja_la_cobertura() -> None:
    r = comparar(
        FICHA, ProductDnaDraft(attributes=(_a("materials", "acero galvanizado", "INFERRED"),))
    )
    assert r.con_localizador == 0 and r.afirmados == 1


def test_sin_casos_es_desconocido_no_cero() -> None:
    m = Medida("x", 0, 0)
    assert m.porcentaje is None
    assert "desconocido" in m.linea()


def test_cada_medida_lleva_su_margen() -> None:
    assert "±" in Medida("x", 3, 4).linea()


def test_el_script_de_product_dna_corre_con_un_proveedor_de_prueba(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un modelo obediente que devuelve justo lo esperado: todo al 100 %."""
    from apps.evaluacion import product_dna_39
    from core.llm.types import CallMetadata, StructuredResponse

    class Obediente:
        name = "fake"

        def generate_structured(self, messages: Any, schema: type, **k: Any) -> Any:
            texto = messages[0].content
            ficha = next(f for f in FICHAS if f.texto in texto)
            atributos = [
                {"name": n, "value": v, "status": "OBSERVED", "evidence_reference": "ficha"}
                for n, v in ficha.esperado.items()
            ]
            return StructuredResponse[schema](  # type: ignore[valid-type]
                data=schema(attributes=atributos),
                metadata=CallMetadata(model_provider="fake", model_name="fake-1"),
            )

    monkeypatch.setattr(product_dna_39, "get_default_provider", Obediente)
    assert product_dna_39.main([]) == 0

    salida = capsys.readouterr().out
    assert "SYNTHETIC DEMO DATA" in salida
    assert "field extraction accuracy" in salida and "100.00 %" in salida
    assert f"{len(FICHAS)} fichas" in salida


# ── Búsqueda jurídica ───────────────────────────────────────────────────────


def _pregunta(**over: Any) -> PreguntaEtiquetada:
    campos: dict[str, Any] = {
        "id": "p",
        "pregunta": "¿qué?",
        "fecha": date(2026, 8, 4),
        "esperado": (("Ley Aduanera", "Artículo 36-A"),),
        "validado_por": "cesar",
    }
    campos.update(over)
    return PreguntaEtiquetada(**campos)


def _respuesta(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "evidence": [
            {"documento": "Ley Aduanera", "articulo": "36-A", "n": 1},
            {"documento": "Ley Aduanera", "articulo": "59", "n": 2},
        ],
        "sources": [{"documento": "Ley Aduanera", "articulo": "36-A", "n": 1}],
        "redacta_respuesta": True,
        "confidence": "1.00",
        "missing_information": [],
    }
    base.update(over)
    return base


def test_el_articulo_se_compara_normalizado() -> None:
    assert es_el_esperado(
        {"documento": "Ley Aduanera (DOF)", "articulo": "36-A"}, ("ley aduanera", "Art. 36-A")
    )
    assert not es_el_esperado(
        {"documento": "Ley Aduanera", "articulo": "36"}, ("Ley Aduanera", "36-A")
    )


def test_una_respuesta_que_recupera_y_cita_lo_que_responde() -> None:
    r = evaluar(_pregunta(), _respuesta())
    assert r.recupero is True
    assert (r.citadas_pertinentes, r.citadas) == (1, 1)
    assert r.sin_sustento is False


def test_una_oracion_sin_cita_es_respuesta_sin_sustento() -> None:
    """La misma definición del ADR 0010: confidence < 1."""
    assert evaluar(_pregunta(), _respuesta(confidence="0.67")).sin_sustento is True


def test_contestar_sin_corpus_sin_declarar_que_falta_es_sin_sustento() -> None:
    sin_corpus = _pregunta(esperado=(), sin_corpus=True)
    assert evaluar(sin_corpus, _respuesta()).sin_sustento is True
    assert (
        evaluar(sin_corpus, _respuesta(missing_information=["PROSEC no cargado"])).sin_sustento
        is False
    )
    assert evaluar(sin_corpus, _respuesta()).recupero is None


def test_decir_que_no_hay_evidencia_no_es_respuesta_sin_sustento() -> None:
    r = evaluar(_pregunta(), _respuesta(redacta_respuesta=False, confidence="0.00", sources=[]))
    assert r.entregada is False and r.sin_sustento is False


def test_una_pregunta_sin_firma_no_esta_etiquetada() -> None:
    assert _pregunta(validado_por=None).etiquetada is False
    assert _pregunta(esperado=()).etiquetada is False, "firmada pero sin respuesta"


def test_el_reporte_suma_las_tres_medidas() -> None:
    a = evaluar(_pregunta(), _respuesta())
    b = evaluar(_pregunta(), _respuesta(confidence="0.50", evidence=[], sources=[]))
    reporte = ReporteJuridico(preguntas=(a, b))

    assert reporte.acierto_de_recuperacion.porcentaje == Decimal("50.00")
    assert reporte.precision_de_fuentes.porcentaje == Decimal("100.00")
    assert reporte.respuestas_sin_sustento.porcentaje == Decimal("50.00")


def test_las_preguntas_del_repositorio_cargan_y_ninguna_finge_estar_etiquetada() -> None:
    """Hoy ninguna está firmada: el script tiene que decirlo, no medir."""
    from apps.evaluacion.busqueda_juridica_39 import cargar

    preguntas = cargar()
    assert preguntas
    for p in preguntas:
        if p.validado_por is None:
            assert not p.etiquetada


def test_sin_etiquetas_el_script_no_llama_a_la_api(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from apps.evaluacion import busqueda_juridica_39

    monkeypatch.setattr(
        busqueda_juridica_39,
        "cargar",
        lambda: [_pregunta(validado_por=None), _pregunta(id="q", validado_por=None)],
    )
    assert busqueda_juridica_39.main(["--api", "http://127.0.0.1:1"]) == 0

    salida = capsys.readouterr().out
    assert "0 pregunta(s) etiquetadas · 2 esperan etiqueta" in salida
    assert "no hay métrica" in salida
