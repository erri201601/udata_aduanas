"""Tests de higiene del repositorio.

Verifican reglas del documento rector que un linter no cubre: que no se filtren
secretos y que la estructura acordada exista.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

# §7 maestro / §4 Persona 1.
DIRECTORIOS_ESPERADOS = [
    "apps/api",
    "apps/web",
    "core/classification",
    "core/rgi_engine",
    "core/product_dna",
    "core/evidence",
    "core/taxation",
    "core/audit",
    "core/shadow",
    "core/opportunity",
    "ingestion/snice",
    "ingestion/dof",
    "ingestion/vucem",
    "ingestion/sat",
    "ingestion/anam",
    "ingestion/datamexico",
    "ingestion/banxico",
    "ingestion/cbp_cross",
    "ingestion/ebti",
    "ingestion/wco",
    "rag",
    "graph",
    "synthetic",
    "database/migrations",
    "database/models",
    "database/seeds",
    "schemas",
    "prompts",
    "tests",
    "docs",
    "infrastructure/docker",
    "infrastructure/scripts",
]


def test_estructura_del_repositorio_completa(repo_root: Path) -> None:
    """La estructura de §7 debe existir entera."""
    faltantes = [d for d in DIRECTORIOS_ESPERADOS if not (repo_root / d).is_dir()]

    assert not faltantes, f"directorios ausentes: {faltantes}"


def test_env_no_esta_versionado(repo_root: Path) -> None:
    """`.env` jamás debe entrar a Git (§40 maestro, §10.10 Persona 1)."""
    resultado = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode != 0, ".env está versionado — hay que purgarlo del historial"


def test_env_example_no_contiene_secretos_reales(repo_root: Path) -> None:
    """`.env.example` es plantilla: sus campos de secreto van vacíos."""
    contenido = (repo_root / ".env.example").read_text(encoding="utf-8")

    campos_secretos = (
        "POSTGRES_PASSWORD",
        "NEO4J_PASSWORD",
        "REDIS_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
    )
    con_valor = [
        linea
        for linea in contenido.splitlines()
        if any(
            linea.startswith(f"{campo}=") and linea.split("=", 1)[1].strip()
            for campo in campos_secretos
        )
    ]

    assert not con_valor, f"valores reales en .env.example: {con_valor}"


@pytest.mark.parametrize(
    "documento",
    ["docs/00_ADUANERO_OS_PROMPT_MAESTRO.md", "docs/01_PERSONA_1_TECH_LEAD.md"],
)
def test_documentos_rectores_presentes_y_utf8(repo_root: Path, documento: str) -> None:
    """Los documentos rectores deben existir y leerse como UTF-8 válido."""
    ruta = repo_root / documento

    assert ruta.is_file(), f"falta {documento}"
    texto = ruta.read_text(encoding="utf-8")
    assert len(texto) > 1000
    # Mojibake típico de leer UTF-8 como latin-1.
    assert "Ã" not in texto, f"{documento} tiene codificación corrupta"
