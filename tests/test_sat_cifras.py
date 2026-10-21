"""SAT Datos Abiertos: cifras de comercio exterior (ADR 0021).

Los fragmentos son filas verbatim de los `.xls` reales (21-oct-2026), con el
cambio de 2010 a 2011: lo que prueba que los pedimentos se acumulan en el año
y vuelven a empezar en enero.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from ingestion.sat.cifras import (
    ARCHIVOS,
    Archivo,
    CifrasIlegiblesError,
    es_acumulada_por_los_datos,
    leer,
    leer_filas,
)

from tests.fixtures.sat_cifras_fragmentos import IMPORTACION, RECAUDACION

pytestmark = pytest.mark.unit

ARCH_IMPORTACION, _, ARCH_RECAUDACION = ARCHIVOS


def test_lee_los_pedimentos_de_2010_a_agosto_de_2026() -> None:
    cifras = leer_filas(IMPORTACION, ARCH_IMPORTACION)
    assert (cifras[0].anio, cifras[0].mes, cifras[0].valor) == (2010, 1, Decimal("0.388878"))
    assert (cifras[-1].anio, cifras[-1].mes, cifras[-1].valor) == (2026, 8, Decimal("5.305579"))
    assert all(c.unidad == "millones de pedimentos" and c.acumulada for c in cifras)


def test_el_float_de_xlrd_llega_a_decimal_sin_ruido() -> None:
    iva = next(c for c in leer_filas(RECAUDACION, ARCH_RECAUDACION) if c.serie == "RECAUDACION_IVA")
    assert iva.valor == Decimal("15562.345092")


def test_los_pedimentos_son_acumulados_y_la_recaudacion_no_lo_dicen_los_datos() -> None:
    assert es_acumulada_por_los_datos(leer_filas(IMPORTACION, ARCH_IMPORTACION))
    iva = [c for c in leer_filas(RECAUDACION, ARCH_RECAUDACION) if c.serie == "RECAUDACION_IVA"]
    assert not es_acumulada_por_los_datos(iva)


def test_la_recaudacion_tiene_una_serie_por_impuesto() -> None:
    agosto = {
        c.serie: c.valor
        for c in leer_filas(RECAUDACION, ARCH_RECAUDACION)
        if (c.anio, c.mes) == (2026, 8)
    }
    assert agosto["RECAUDACION_IGI"] == Decimal("17213.380345")
    assert set(agosto) == set(ARCH_RECAUDACION.series)


def test_las_notas_del_sat_viajan_verbatim() -> None:
    nota = leer_filas(IMPORTACION, ARCH_IMPORTACION)[0].notas or ""
    assert "Agencia Nacional de Aduanas" in nota


def test_una_serie_acumulada_que_baja_detiene_la_carga() -> None:
    """Leer la recaudación como si fuera acumulada tiene que fallar."""
    disfrazada = Archivo(ARCH_RECAUDACION.nombre, ARCH_RECAUDACION.series, "x", True)
    with pytest.raises(CifrasIlegiblesError, match="NEEDS_VALIDATION"):
        leer_filas(RECAUDACION, disfrazada)


def test_sin_filas_de_mes_no_se_inventa_nada() -> None:
    with pytest.raises(CifrasIlegiblesError):
        leer_filas([["", "Declaraciones y pagos"]], ARCH_IMPORTACION)


def test_un_archivo_que_no_es_xls_falla() -> None:
    with pytest.raises(Exception):  # noqa: B017 — lo rechaza xlrd
        leer(b"no es un xls", ARCH_IMPORTACION)
