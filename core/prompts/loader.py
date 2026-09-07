"""Carga y versionado de prompts (§30 maestro).

Todo prompt del producto se versiona y toda decisión registra con qué
`prompt_id` y `prompt_version` se produjo (§17). Un prompt que cambia sin
cambiar de versión rompe la trazabilidad hacia atrás: las decisiones ya
tomadas dejarían de ser reproducibles.

Convención de ficheros:

    prompts/<familia>/<nombre>.v<version>.md

    prompts/product_dna/extract.v0.1.md   ->  prompt_id "product_dna.extract"
                                              prompt_version "0.1"

Cada fichero abre con una cabecera delimitada por `---` y pares `clave: valor`.
Se parsea a mano, sin YAML, para no añadir una dependencia por cinco campos.
"""

from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterator

# `extract.v0.1.md` -> nombre "extract", versión "0.1"
_FILENAME = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<version>\d+\.\d+)\.md$")
_HEADER = re.compile(r"^---\s*\n(?P<header>.*?)\n---\s*\n(?P<body>.*)$", re.DOTALL)

ENV_PROMPTS_DIR = "ADUANERO_PROMPTS_DIR"


class PromptError(Exception):
    """Fallo al cargar o resolver un prompt."""


class Prompt(BaseModel):
    """Un prompt versionado, listo para usarse."""

    model_config = ConfigDict(frozen=True)

    prompt_id: str
    prompt_version: str
    description: str = ""
    body: str
    content_hash: str
    path: Path

    def render(self, **variables: object) -> str:
        """Sustituye `$variable` en el cuerpo.

        Se usa `string.Template` y no `str.format` porque los prompts llevan
        ejemplos de JSON, y las llaves de `format` chocarían con ellos.
        """
        try:
            return Template(self.body).substitute({k: str(v) for k, v in variables.items()})
        except KeyError as exc:
            raise PromptError(
                f"{self.prompt_id} v{self.prompt_version}: falta la variable {exc}"
            ) from exc

    @property
    def reference(self) -> dict[str, str]:
        """Campos de trazabilidad para registrar junto a la decisión (§17)."""
        return {
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "content_hash": self.content_hash,
        }


def default_prompts_dir() -> Path:
    """Directorio `prompts/` del repositorio, salvo que `.env` diga otra cosa."""
    override = os.getenv(ENV_PROMPTS_DIR)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "prompts"


def _parse_version(version: str) -> tuple[int, ...]:
    """`"0.10"` ordena después de `"0.9"`, que es lo que no hace el orden textual."""
    return tuple(int(part) for part in version.split("."))


def _read_prompt(path: Path, family: str, name: str, version: str) -> Prompt:
    """Lee un fichero de prompt y valida su cabecera."""
    raw = path.read_text(encoding="utf-8")
    match = _HEADER.match(raw)
    if match is None:
        raise PromptError(f"{path}: falta la cabecera delimitada por '---'")

    header: dict[str, str] = {}
    for line in match.group("header").splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        header[key.strip()] = value.strip()

    body = match.group("body").strip()
    declared_id = header.get("prompt_id", "")
    expected_id = f"{family}.{name}"
    if declared_id and declared_id != expected_id:
        raise PromptError(
            f"{path}: prompt_id '{declared_id}' no coincide con la ruta '{expected_id}'"
        )
    declared_version = header.get("prompt_version", "")
    if declared_version and declared_version != version:
        raise PromptError(
            f"{path}: prompt_version '{declared_version}' no coincide con el nombre '{version}'"
        )

    return Prompt(
        prompt_id=expected_id,
        prompt_version=version,
        description=header.get("description", ""),
        body=body,
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        path=path,
    )


class PromptRegistry:
    """Índice de los prompts en disco."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_prompts_dir()

    def _iter_files(self) -> Iterator[tuple[str, str, str, Path]]:
        """(familia, nombre, versión, ruta) de cada prompt bien nombrado."""
        if not self.root.is_dir():
            return
        for path in sorted(self.root.glob("*/*.md")):
            match = _FILENAME.match(path.name)
            if match is None:
                continue
            yield path.parent.name, match.group("name"), match.group("version"), path

    def versions(self, prompt_id: str) -> list[str]:
        """Versiones disponibles de un prompt, de la más antigua a la más nueva."""
        found = [
            version
            for family, name, version, _ in self._iter_files()
            if f"{family}.{name}" == prompt_id
        ]
        return sorted(found, key=_parse_version)

    def list_ids(self) -> list[str]:
        """Todos los `prompt_id` registrados."""
        return sorted({f"{family}.{name}" for family, name, _, _ in self._iter_files()})

    def get(self, prompt_id: str, version: str | None = None) -> Prompt:
        """Carga un prompt. Sin `version`, la más alta disponible.

        En producción conviene fijar la versión: así una decisión histórica se
        puede reproducir aunque el prompt haya avanzado (§14 maestro).
        """
        candidates = {
            version_found: (family, name, path)
            for family, name, version_found, path in self._iter_files()
            if f"{family}.{name}" == prompt_id
        }
        if not candidates:
            raise PromptError(f"prompt desconocido: {prompt_id!r}; disponibles: {self.list_ids()}")

        chosen = version or max(candidates, key=_parse_version)
        if chosen not in candidates:
            raise PromptError(
                f"{prompt_id}: no existe la versión {chosen!r}; "
                f"disponibles: {sorted(candidates, key=_parse_version)}"
            )

        family, name, path = candidates[chosen]
        return _read_prompt(path, family, name, chosen)


@lru_cache
def _cached_registry(root: Path | None) -> PromptRegistry:
    """Registro cacheado: los prompts no cambian en caliente."""
    return PromptRegistry(root)


def load_prompt(prompt_id: str, version: str | None = None, *, root: Path | None = None) -> Prompt:
    """Atajo para cargar un prompt del registro por defecto."""
    return _cached_registry(root).get(prompt_id, version)
