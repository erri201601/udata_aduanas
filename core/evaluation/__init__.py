"""Evaluación de acierto del clasificador contra verdad externa (§39)."""

from core.evaluation.harness import (
    NOMENCLATURA_ADMITIDA,
    CasoDeEvaluacion,
    Clasificacion,
    ExtraccionConUso,
    Reporte,
    ResultadoDeCaso,
    Tarifas,
    UsoDeCaso,
    estimar_costo,
    evaluar,
    motivo_de_exclusion,
)
from core.evaluation.ports import FuenteDeCasos

__all__ = [
    "NOMENCLATURA_ADMITIDA",
    "CasoDeEvaluacion",
    "Clasificacion",
    "ExtraccionConUso",
    "FuenteDeCasos",
    "Reporte",
    "ResultadoDeCaso",
    "Tarifas",
    "UsoDeCaso",
    "estimar_costo",
    "evaluar",
    "motivo_de_exclusion",
]
