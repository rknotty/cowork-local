"""Tool definitions, tiers and the registry.

Small models choose tools from their descriptions, so each definition has a
verb-first name, a two-sentence description and a strict JSON schema with
enums wherever possible (plan section 9, step 1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from orchestrator.errors import ToolNotFoundError

if TYPE_CHECKING:
    from orchestrator.toolkit.context import ToolContext


class ToolTier(IntEnum):
    """Risk tier. Decides the default approval policy."""

    READ = 0
    WRITE = 1
    EXECUTE = 2
    EXTERNAL = 3


@dataclass(frozen=True)
class ToolOutput:
    """What a tool hands back to the model."""

    text: str
    # Where the full output can be re-read if `text` is truncated.
    file_reference: str = ""


ToolHandler = Callable[["ToolContext", dict[str, Any]], Awaitable[ToolOutput]]


@dataclass(frozen=True)
class ToolDefinition:
    """One callable tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    tier: ToolTier
    handler: ToolHandler
    # Name of the argument holding the path this call acts on, if any. The
    # router uses it for the workspace check and the approval prompt.
    target_argument: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def to_openai_tool(self) -> dict[str, object]:
        """Render in the OpenAI tool-definition wire format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def object_schema(
    properties: dict[str, dict[str, Any]], required: list[str]
) -> dict[str, Any]:
    """Build a strict object schema: unknown arguments are rejected."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


class ToolRegistry:
    """All registered tools, split into core (always sent) and deferred."""

    def __init__(self, core_tool_names: tuple[str, ...]) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._core_tool_names = core_tool_names

    def register(self, definition: ToolDefinition) -> None:
        """Add a tool. A later registration with the same name replaces it."""
        self._definitions[definition.name] = definition

    def get(self, tool_name: str) -> ToolDefinition:
        """Look a tool up by name.

        Raises:
            ToolNotFoundError: Carrying the valid names, so the repair
                message can tell the model what it may call instead.
        """
        definition = self._definitions.get(tool_name)
        if definition is None:
            raise ToolNotFoundError(
                "tool not registered",
                tool_name=tool_name,
                valid_tool_names=sorted(self._definitions),
            )
        return definition

    def find(self, tool_name: str) -> ToolDefinition | None:
        """Look a tool up by name, returning None if it is not registered."""
        return self._definitions.get(tool_name)

    def core_definitions(self) -> list[ToolDefinition]:
        """Tools sent to the model on every turn."""
        return [
            self._definitions[name]
            for name in self._core_tool_names
            if name in self._definitions
        ]

    def deferred_definitions(self) -> list[ToolDefinition]:
        """Tools the model must discover through `find_tool`."""
        return [
            definition
            for name, definition in sorted(self._definitions.items())
            if name not in self._core_tool_names
        ]

    def search_deferred(self, query: str, limit: int = 4) -> list[ToolDefinition]:
        """Keyword search over deferred tool names, descriptions and keywords."""
        query_terms = [term for term in query.lower().split() if len(term) > 1]
        scored: list[tuple[int, ToolDefinition]] = []
        for definition in self.deferred_definitions():
            searchable_text = " ".join(
                [definition.name, definition.description, *definition.keywords]
            ).lower()
            score = sum(searchable_text.count(term) for term in query_terms)
            if score > 0:
                scored.append((score, definition))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [definition for _, definition in scored[:limit]]
