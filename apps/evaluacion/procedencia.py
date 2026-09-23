"""Cuándo se midió y con qué código. El sello que viaja con todo número.

El 22 de septiembre el recall pasó de 27.78 % a 83.33 % en unas horas, y no
porque el motor mejorara solo: cambió el código y se volvió a auditar. Dos
números del mismo día parecen contradecirse cuando en realidad miden cosas
distintas, y sin fecha ni revisión no se pueden situar después.

Vive aparte porque lo usan las DOS métricas del §26 —detección y hs_accuracy—
y una segunda copia se desincroniza el día que alguien cambie el formato.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import NamedTuple


class Procedencia(NamedTuple):
    """Cuándo se midió y con qué código. Sin esto el número no es reproducible."""

    momento: str
    revision: str
    rama: str
    sucio: bool


def _git(*argumentos: str) -> str:
    """Lo que diga git, o vacío. Que no haya git no puede romper una medición."""
    try:
        salida = subprocess.run(
            ["git", *argumentos],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return salida.stdout.strip() if salida.returncode == 0 else ""


def procedencia() -> Procedencia:
    return Procedencia(
        momento=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        revision=_git("rev-parse", "--short", "HEAD") or "desconocida",
        rama=_git("rev-parse", "--abbrev-ref", "HEAD") or "desconocida",
        sucio=bool(_git("status", "--porcelain")),
    )


def linea_de_procedencia(p: Procedencia) -> str:
    """Una línea que viaja con el número cuando alguien lo pega en un chat.

    El 22 de septiembre el recall pasó de 27.78 % a 83.33 % en unas horas, y no
    porque el motor mejorara solo: cambió el código y se volvió a auditar. Un
    reporte sin fecha ni revisión no se puede situar después, y dos números del
    mismo día parecen contradecirse cuando en realidad miden cosas distintas.

    El árbol sucio se declara: si hay cambios sin commitear, ese número no sale
    de ninguna revisión que otro pueda recuperar.
    """
    linea = f"MEDIDO  {p.momento} · código {p.revision} ({p.rama})"
    if p.sucio:
        linea += "  ← CON CAMBIOS SIN COMMITEAR: no se puede reproducir desde esa revisión"
    return linea
