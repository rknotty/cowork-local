"""Skill, memory and knowledge tools."""

from __future__ import annotations

from typing import Any

from orchestrator.events import AgentEvent, EventType
from orchestrator.knowledge.index import SearchHit
from orchestrator.toolkit.context import ToolContext
from orchestrator.toolkit.registry import (
    ToolDefinition,
    ToolOutput,
    ToolRegistry,
    ToolTier,
    object_schema,
)

MAX_HIT_CHARACTERS = 700


async def load_skill(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Return the body of a skill's SKILL.md."""
    skill = context.services.skills.get(arguments["name"])
    context.loaded_skill_names.add(skill.name)
    context.discovered_tool_names.update(skill.allowed_tools)
    tools_note = (
        f"\n\n[Tools available for this skill: {', '.join(skill.allowed_tools)}]"
        if skill.allowed_tools
        else ""
    )
    return ToolOutput(skill.body + tools_note)


async def read_skill_file(
    context: ToolContext, arguments: dict[str, Any]
) -> ToolOutput:
    """Return a reference file from inside a skill folder."""
    return ToolOutput(
        context.services.skills.read_reference_file(
            arguments["name"], arguments["path"]
        )
    )


async def save_memory(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Write a memory file. Refuses credentials and special category data."""
    context.services.memory.save(
        arguments["name"], arguments["description"], arguments["content"]
    )
    return ToolOutput(f"Saved memory '{arguments['name']}'.")


def _announce_access(context: ToolContext, query: str, hits: list[SearchHit]) -> None:
    """Tell the interface which indexed files a search drew passages from.

    Drives the live index map. Files are listed in rank order, once each,
    with how many of the returned passages came from them.
    """
    files: dict[str, dict[str, object]] = {}
    for hit in hits:
        entry = files.setdefault(
            hit.file_path,
            {
                "file_path": hit.file_path,
                "passage_count": 0,
                "best_score": round(hit.score, 4),
            },
        )
        entry["passage_count"] = int(str(entry["passage_count"])) + 1
    context.emit(
        AgentEvent(
            EventType.KNOWLEDGE_ACCESS, {"query": query, "files": list(files.values())}
        )
    )


async def search_knowledge(
    context: ToolContext, arguments: dict[str, Any]
) -> ToolOutput:
    """Search indexed documents and return passages with their sources."""
    hits = await context.services.knowledge.search(arguments["query"])
    _announce_access(context, arguments["query"], hits)
    if not hits:
        return ToolOutput(
            "No indexed passages matched. The connected folders may not be "
            "indexed yet, or the answer is not in them."
        )
    passages = [
        f"[source: {hit.file_path} | section: {hit.heading_path or '(top)'}]\n"
        f"{hit.text[:MAX_HIT_CHARACTERS]}"
        for hit in hits
    ]
    return ToolOutput(
        "\n\n".join(passages) + "\n\nCite the source path for each fact you use."
    )


def register_knowledge_tools(registry: ToolRegistry) -> None:
    """Register load_skill, read_skill_file, save_memory and search_knowledge."""
    name_property = {"type": "string", "pattern": "^[a-z0-9]+(-[a-z0-9]+)*$"}
    registry.register(
        ToolDefinition(
            name="load_skill",
            description=(
                "Load the full instructions for a skill named in the skill list. "
                "Do this before starting any task a skill matches."
            ),
            parameters=object_schema({"name": name_property}, ["name"]),
            tier=ToolTier.READ,
            handler=load_skill,
        )
    )
    registry.register(
        ToolDefinition(
            name="read_skill_file",
            description=(
                "Read a reference file that a loaded skill mentions. "
                "The path is relative to the skill's own folder."
            ),
            parameters=object_schema(
                {"name": name_property, "path": {"type": "string"}}, ["name", "path"]
            ),
            tier=ToolTier.READ,
            handler=read_skill_file,
            keywords=("skill", "reference", "template"),
        )
    )
    registry.register(
        ToolDefinition(
            name="save_memory",
            description=(
                "Remember a fact for future sessions, only when the user asks "
                "you to remember it. Never store passwords, keys or health data."
            ),
            parameters=object_schema(
                {
                    "name": name_property,
                    "description": {"type": "string", "minLength": 5, "maxLength": 160},
                    "content": {"type": "string", "minLength": 1, "maxLength": 4000},
                },
                ["name", "description", "content"],
            ),
            tier=ToolTier.WRITE,
            handler=save_memory,
            keywords=("remember", "memory", "preference", "note"),
        )
    )
    registry.register(
        ToolDefinition(
            name="search_knowledge",
            description=(
                "Search the user's indexed documents for passages relevant to "
                "a question. Returns passages with source file paths to cite."
            ),
            parameters=object_schema(
                {"query": {"type": "string", "minLength": 3}}, ["query"]
            ),
            tier=ToolTier.READ,
            handler=search_knowledge,
            keywords=("knowledge", "search", "documents", "find", "lookup", "policy"),
        )
    )
