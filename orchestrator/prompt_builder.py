"""Layered system prompt assembly (plan section 7, step 2).

Layers, in order: identity and rules, skill index (names and one-line
descriptions only), memory, working folder listing. The tool list travels in
the API's `tools` field rather than in the prompt text. Each layer's token
count is measured so an oversized layer is visible in the logs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from orchestrator.context_budget import estimate_tokens
from orchestrator.errors import ConfigurationError
from orchestrator.memory import MemoryFile
from orchestrator.paths import TO_DELETE_FOLDER_NAME

logger = logging.getLogger(__name__)

MAX_WORKSPACE_ENTRIES = 40
REQUIRED_PROMPT_KEYS = (
    "identity_and_rules",
    "skill_index_heading",
    "memory_heading",
    "workspace_heading",
    "connected_folders_heading",
    "compaction_instruction",
    "extract_instruction",
    "merge_instruction",
    "title_instruction",
)


@dataclass(frozen=True)
class SystemPrompt:
    """The assembled prompt and the measured size of each layer."""

    text: str
    layer_tokens: dict[str, int]

    @property
    def total_tokens(self) -> int:
        """Estimated tokens across all layers."""
        return sum(self.layer_tokens.values())


@lru_cache(maxsize=4)
def load_prompts(repository_root: Path) -> dict[str, str]:
    """Read `config/prompts.yaml`.

    Raises:
        ConfigurationError: If the file is missing or lacks a required key.
    """
    prompts_path = repository_root / "config" / "prompts.yaml"
    try:
        loaded = yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, yaml.YAMLError) as exc:
        raise ConfigurationError("prompts.yaml missing or invalid") from exc
    missing_keys = [key for key in REQUIRED_PROMPT_KEYS if key not in (loaded or {})]
    if missing_keys:
        raise ConfigurationError("prompts.yaml keys missing", missing_keys=missing_keys)
    return {key: str(loaded[key]).strip() for key in REQUIRED_PROMPT_KEYS}


def list_workspace(workspace: Path) -> str:
    """A short listing of the workspace so the model knows what is there."""
    entries = []
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and TO_DELETE_FOLDER_NAME not in path.parts:
            entries.append(path.relative_to(workspace).as_posix())
        if len(entries) >= MAX_WORKSPACE_ENTRIES:
            entries.append("[... more files not shown; use list_dir]")
            break
    return "\n".join(entries) or "(empty)"


def build_system_prompt(
    prompts: dict[str, str],
    skill_index_text: str,
    memory_files: list[MemoryFile],
    workspace: Path,
    connected_folders: list[str],
) -> SystemPrompt:
    """Assemble the system prompt and measure each layer."""
    layers: dict[str, str] = {"identity_and_rules": prompts["identity_and_rules"]}
    if skill_index_text:
        layers["skill_index"] = f"{prompts['skill_index_heading']}\n{skill_index_text}"
    if memory_files:
        memory_text = "\n\n".join(
            f"[{memory_file.name}]\n{memory_file.content}"
            for memory_file in memory_files
        )
        layers["memory"] = f"{prompts['memory_heading']}\n{memory_text}"
    layers["workspace"] = f"{prompts['workspace_heading']}\n{list_workspace(workspace)}"
    if connected_folders:
        folder_lines = "\n".join(connected_folders)
        layers["connected_folders"] = (
            f"{prompts['connected_folders_heading']}\n{folder_lines}"
        )
    layer_tokens = {name: estimate_tokens(text) for name, text in layers.items()}
    logger.debug("System prompt assembled", extra={"layer_tokens": layer_tokens})
    return SystemPrompt(text="\n\n".join(layers.values()), layer_tokens=layer_tokens)
