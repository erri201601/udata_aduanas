"""Carga y versionado de prompts (§30 maestro)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from core.prompts import Prompt, PromptError, PromptRegistry, load_prompt

if TYPE_CHECKING:
    from pathlib import Path


def _escribir(root: Path, familia: str, nombre: str, version: str, cuerpo: str = "hola") -> Path:
    directorio = root / familia
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / f"{nombre}.v{version}.md"
    ruta.write_text(
        f"---\nprompt_id: {familia}.{nombre}\nprompt_version: {version}\n"
        f"description: prueba\n---\n{cuerpo}\n",
        encoding="utf-8",
    )
    return ruta


# ── El prompt real del repositorio ───────────────────────────────────────────


def test_el_prompt_de_product_dna_existe_y_carga() -> None:
    prompt = load_prompt("product_dna.extract")

    assert prompt.prompt_id == "product_dna.extract"
    assert prompt.prompt_version == "0.1"
    assert prompt.content_hash


def test_el_prompt_declara_los_cuatro_estados_de_product_dna() -> None:
    """§16 y §7 de Persona 3: una inferencia jamás se presenta como hecho."""
    cuerpo = load_prompt("product_dna.extract").body

    for estado in ("OBSERVED", "EXTRACTED", "INFERRED", "MISSING"):
        assert estado in cuerpo


def test_reference_trae_lo_que_pide_la_trazabilidad() -> None:
    """§17: la decisión registra prompt_id, prompt_version y hash."""
    referencia = load_prompt("product_dna.extract").reference

    assert set(referencia) == {"prompt_id", "prompt_version", "content_hash"}


# ── Versionado ───────────────────────────────────────────────────────────────


def test_sin_version_se_carga_la_mas_alta(tmp_path: Path) -> None:
    _escribir(tmp_path, "product_dna", "extract", "0.1")
    _escribir(tmp_path, "product_dna", "extract", "0.2")

    assert PromptRegistry(tmp_path).get("product_dna.extract").prompt_version == "0.2"


def test_las_versiones_ordenan_por_numero_no_por_texto(tmp_path: Path) -> None:
    """`0.10` es posterior a `0.9`, cosa que el orden alfabético invierte."""
    _escribir(tmp_path, "product_dna", "extract", "0.9")
    _escribir(tmp_path, "product_dna", "extract", "0.10")

    registro = PromptRegistry(tmp_path)

    assert registro.versions("product_dna.extract") == ["0.9", "0.10"]
    assert registro.get("product_dna.extract").prompt_version == "0.10"


def test_se_puede_fijar_una_version_historica(tmp_path: Path) -> None:
    """§14: reproducir una decisión pasada exige poder pedir su prompt exacto."""
    _escribir(tmp_path, "product_dna", "extract", "0.1")
    _escribir(tmp_path, "product_dna", "extract", "0.2")

    assert PromptRegistry(tmp_path).get("product_dna.extract", "0.1").prompt_version == "0.1"


def test_version_inexistente_falla_y_dice_cuales_hay(tmp_path: Path) -> None:
    _escribir(tmp_path, "product_dna", "extract", "0.1")

    with pytest.raises(PromptError, match=r"0\.1"):
        PromptRegistry(tmp_path).get("product_dna.extract", "9.9")


def test_prompt_desconocido_falla(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="desconocido"):
        PromptRegistry(tmp_path).get("no.existe")


# ── Integridad de la cabecera ────────────────────────────────────────────────


def test_cabecera_que_miente_sobre_su_version_se_rechaza(tmp_path: Path) -> None:
    """Si el nombre y la cabecera divergen, la trazabilidad ya es falsa."""
    directorio = tmp_path / "product_dna"
    directorio.mkdir(parents=True)
    (directorio / "extract.v0.1.md").write_text(
        "---\nprompt_id: product_dna.extract\nprompt_version: 0.7\n---\ncuerpo\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="no coincide"):
        PromptRegistry(tmp_path).get("product_dna.extract")


def test_fichero_sin_cabecera_se_rechaza(tmp_path: Path) -> None:
    directorio = tmp_path / "product_dna"
    directorio.mkdir(parents=True)
    (directorio / "extract.v0.1.md").write_text("solo cuerpo\n", encoding="utf-8")

    with pytest.raises(PromptError, match="cabecera"):
        PromptRegistry(tmp_path).get("product_dna.extract")


def test_ficheros_mal_nombrados_se_ignoran(tmp_path: Path) -> None:
    """Un README dentro de la familia no es un prompt."""
    _escribir(tmp_path, "product_dna", "extract", "0.1")
    (tmp_path / "product_dna" / "README.md").write_text("notas", encoding="utf-8")

    assert PromptRegistry(tmp_path).list_ids() == ["product_dna.extract"]


# ── Render ───────────────────────────────────────────────────────────────────


def test_render_sustituye_variables(tmp_path: Path) -> None:
    _escribir(tmp_path, "product_dna", "extract", "0.1", cuerpo="Documento:\n$documento")

    prompt = PromptRegistry(tmp_path).get("product_dna.extract")

    assert prompt.render(documento="ficha X").endswith("ficha X")


def test_render_no_rompe_con_llaves_de_json(tmp_path: Path) -> None:
    """Los prompts llevan ejemplos de JSON: `str.format` los destrozaría."""
    _escribir(tmp_path, "product_dna", "extract", "0.1", cuerpo='{"a": 1}\n$documento')

    prompt = PromptRegistry(tmp_path).get("product_dna.extract")

    assert '{"a": 1}' in prompt.render(documento="x")


def test_falta_una_variable_y_se_dice_cual(tmp_path: Path) -> None:
    _escribir(tmp_path, "product_dna", "extract", "0.1", cuerpo="$documento y $imagen")

    prompt = PromptRegistry(tmp_path).get("product_dna.extract")

    with pytest.raises(PromptError, match="imagen"):
        prompt.render(documento="x")


def test_el_prompt_es_inmutable() -> None:
    """Un prompt cargado no se edita en caliente: se publica otra versión."""
    prompt = load_prompt("product_dna.extract")

    with pytest.raises(ValueError, match="frozen"):
        prompt.body = "otra cosa"  # type: ignore[misc]


def test_registro_vacio_no_revienta(tmp_path: Path) -> None:
    assert PromptRegistry(tmp_path / "no-existe").list_ids() == []


def test_el_tipo_publico_es_estable() -> None:
    assert isinstance(load_prompt("product_dna.extract"), Prompt)
