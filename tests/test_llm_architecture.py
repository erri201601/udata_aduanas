"""La regla dura de §29, comprobada por la máquina y no por la buena voluntad.

«Ningún SDK de proveedor se importa dentro de `core/` fuera de
`core/llm/providers/`.» Una regla que sólo vive en un documento se rompe en el
tercer sprint; ésta falla el build.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# SDK de proveedores de IA. Ninguno debe aparecer en `core/`.
SDK_PROHIBIDOS = frozenset(
    {
        "anthropic",
        "openai",
        "google",
        "cohere",
        "mistralai",
        "ollama",
        "litellm",
        "langchain",
        "llama_index",
        "transformers",
    }
)

# httpx sí es dependencia del proyecto, pero el transporte de modelos vive
# encerrado en `core/llm/`. Si aparece en otro punto de `core/`, es que alguien
# está llamando a una API desde el dominio.
TRANSPORTE = frozenset({"httpx"})


def _modulos_importados(archivo: Path) -> set[str]:
    """Módulos raíz importados por un fichero."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    raices: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            raices.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            raices.add(nodo.module.split(".")[0])
    return raices


def _ficheros_de_core(repo_root: Path) -> list[Path]:
    return sorted(p for p in (repo_root / "core").rglob("*.py") if "__pycache__" not in p.parts)


def test_hay_ficheros_que_revisar(repo_root: Path) -> None:
    """Si `core/` se queda vacío, los otros dos tests pasarían por vacuidad."""
    assert _ficheros_de_core(repo_root)


def test_ningun_sdk_de_proveedor_en_core(repo_root: Path) -> None:
    infracciones = [
        f"{archivo.relative_to(repo_root)}: {sorted(prohibidos)}"
        for archivo in _ficheros_de_core(repo_root)
        if (prohibidos := _modulos_importados(archivo) & SDK_PROHIBIDOS)
    ]

    assert not infracciones, (
        f"SDK de proveedor dentro de core/ (§29 maestro, regla 1 de TAREA_P3): {infracciones}"
    )


def test_el_transporte_http_no_sale_de_core_llm(repo_root: Path) -> None:
    permitido = repo_root / "core" / "llm"
    infracciones = [
        str(archivo.relative_to(repo_root))
        for archivo in _ficheros_de_core(repo_root)
        if not archivo.is_relative_to(permitido) and _modulos_importados(archivo) & TRANSPORTE
    ]

    assert not infracciones, (
        f"httpx fuera de core/llm/: el dominio no debe hablar HTTP: {infracciones}"
    )


@pytest.mark.parametrize(
    "modulo",
    ["core.llm", "core.llm.registry", "core.llm.providers", "core.prompts"],
)
def test_importar_no_requiere_credenciales(modulo: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regla 2: sin llaves, el sistema arranca igual."""
    import importlib

    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    importlib.import_module(modulo)
