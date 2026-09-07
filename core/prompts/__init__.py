"""Prompts versionados del producto (§30 maestro)."""

from __future__ import annotations

from core.prompts.loader import (
    Prompt,
    PromptError,
    PromptRegistry,
    default_prompts_dir,
    load_prompt,
)

__all__ = [
    "Prompt",
    "PromptError",
    "PromptRegistry",
    "default_prompts_dir",
    "load_prompt",
]
