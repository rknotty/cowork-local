"""Typed configuration loaded from `config/*.yaml`.

Prompts, model aliases, temperatures and token limits are configuration, not
literals, so a model change is a one-line edit and is visible in review.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from orchestrator.errors import ConfigurationError

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
ROLE_NAMES = ("orchestrator", "utility", "embeddings", "speech")


@dataclass(frozen=True)
class RoleSettings:
    """Model binding for one role."""

    alias: str
    context_limit_tokens: int
    temperature: float
    max_output_tokens: int
    # None leaves the model's chat template default. False turns off a
    # reasoning model's thinking phase (Qwen3 `enable_thinking`).
    is_thinking_enabled: bool | None = None


@dataclass(frozen=True)
class GatewaySettings:
    """Timeouts and locality rule for the model gateway."""

    request_timeout_seconds: float
    load_timeout_seconds: float
    health_timeout_seconds: float
    allowed_hosts: tuple[str, ...]


@dataclass(frozen=True)
class ContextBudgetSettings:
    """Shares of the context window reserved for each prompt layer."""

    system_share: float
    tools_and_skills_share: float
    conversation_share: float
    output_share: float
    skill_index_max_tokens: int


@dataclass(frozen=True)
class SandboxSettings:
    """WSL sandbox identity and limits."""

    distribution: str
    user: str
    wall_clock_timeout_seconds: int
    memory_cap_gb: int
    are_host_builders_allowed: bool


@dataclass(frozen=True)
class McpServerSettings:
    """One allowlisted local MCP server started over stdio."""

    name: str
    command: tuple[str, ...]
    startup_timeout_seconds: float
    call_timeout_seconds: float
    tier_overrides: dict[str, int]


@dataclass(frozen=True)
class Settings:
    """Everything the orchestrator reads from disk at start-up."""

    repository_root: Path
    data_directory: Path
    skills_directory: Path
    builders_directory: Path
    memory_directory: Path
    gateway: GatewaySettings
    roles: dict[str, RoleSettings]
    max_steps: int
    max_repair_attempts: int
    tool_result_max_tokens: int
    context_budget: ContextBudgetSettings
    connected_folders: tuple[Path, ...]
    sandbox: SandboxSettings
    is_web_search_enabled: bool
    core_tool_names: tuple[str, ...]
    mcp_servers: tuple[McpServerSettings, ...]


def _read_yaml(config_path: Path) -> dict[str, Any]:
    try:
        with config_path.open(encoding="utf-8") as config_file:
            loaded = yaml.safe_load(config_file)
    except FileNotFoundError as exc:
        raise ConfigurationError(
            "config file missing", config_path=str(config_path)
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            "config file is not valid YAML", config_path=str(config_path)
        ) from exc
    if not isinstance(loaded, dict):
        raise ConfigurationError(
            "config file must be a mapping", config_path=str(config_path)
        )
    return loaded


def _build_roles(roles_config: dict[str, Any]) -> dict[str, RoleSettings]:
    roles_section = roles_config.get("roles", {})
    missing_roles = [name for name in ROLE_NAMES if name not in roles_section]
    if missing_roles:
        raise ConfigurationError("roles missing", missing_roles=missing_roles)
    return {name: RoleSettings(**roles_section[name]) for name in ROLE_NAMES}


def _build_mcp_servers(mcp_config: dict[str, Any]) -> tuple[McpServerSettings, ...]:
    return tuple(
        McpServerSettings(
            name=server["name"],
            command=tuple(server["command"]),
            startup_timeout_seconds=float(server.get("startup_timeout_seconds", 20)),
            call_timeout_seconds=float(server.get("call_timeout_seconds", 60)),
            tier_overrides=dict(server.get("tier_overrides") or {}),
        )
        for server in mcp_config.get("servers") or []
    )


def load_settings(
    repository_root: Path = REPOSITORY_ROOT,
    data_directory: Path | None = None,
) -> Settings:
    """Load and validate all configuration.

    Args:
        repository_root: Folder holding `config/`, `skills/` and `tools/`.
        data_directory: Override for run-time state. Tests pass a temp folder.

    Raises:
        ConfigurationError: If a file is missing or a section is malformed.
    """
    config_directory = repository_root / "config"
    roles_config = _read_yaml(config_directory / "roles.yaml")
    tools_config = _read_yaml(config_directory / "tools.yaml")
    mcp_config = _read_yaml(config_directory / "mcp.yaml")
    resolved_data_directory = data_directory or repository_root / "data"
    try:
        gateway_section = roles_config["gateway"]
        return Settings(
            repository_root=repository_root,
            data_directory=resolved_data_directory,
            skills_directory=repository_root / "skills",
            builders_directory=repository_root / "tools",
            memory_directory=resolved_data_directory / "memory",
            gateway=GatewaySettings(
                request_timeout_seconds=gateway_section["request_timeout_seconds"],
                load_timeout_seconds=gateway_section["load_timeout_seconds"],
                health_timeout_seconds=gateway_section["health_timeout_seconds"],
                allowed_hosts=tuple(gateway_section["allowed_hosts"]),
            ),
            roles=_build_roles(roles_config),
            max_steps=tools_config["agent"]["max_steps"],
            max_repair_attempts=tools_config["agent"]["max_repair_attempts"],
            tool_result_max_tokens=tools_config["agent"]["tool_result_max_tokens"],
            context_budget=ContextBudgetSettings(**tools_config["context_budget"]),
            connected_folders=tuple(
                Path(folder) for folder in tools_config["folders"]["allowed"] or []
            ),
            sandbox=SandboxSettings(**tools_config["sandbox"]),
            is_web_search_enabled=bool(tools_config["web_search"]["is_enabled"]),
            core_tool_names=tuple(tools_config["core_tools"]),
            mcp_servers=_build_mcp_servers(mcp_config),
        )
    except (KeyError, TypeError) as exc:
        raise ConfigurationError("config section malformed") from exc
