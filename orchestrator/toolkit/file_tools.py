"""File tools: read, list, search, write, edit and soft delete.

All paths go through the allowlist. Nothing here deletes: `remove_file` moves
the file into a `_to_delete` folder so a mistaken call is recoverable (plan
section 9, step 2).
"""

from __future__ import annotations

import fnmatch
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.errors import ToolExecutionError
from orchestrator.events import AgentEvent, EventType
from orchestrator.paths import TO_DELETE_FOLDER_NAME
from orchestrator.toolkit.context import ToolContext
from orchestrator.toolkit.registry import (
    ToolDefinition,
    ToolOutput,
    ToolRegistry,
    ToolTier,
    object_schema,
)

DEFAULT_READ_LINES = 200
MAX_LISTED_ENTRIES = 200
MAX_SEARCH_MATCHES = 30
MAX_SEARCHED_FILE_BYTES = 2_000_000
BINARY_DOCUMENT_SUFFIXES = {".docx", ".pptx", ".xlsx", ".pdf"}

ARTEFACT_KIND_BY_SUFFIX = {
    ".html": "html",
    ".htm": "html",
    ".svg": "svg",
    ".md": "markdown",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
}


def artefact_kind_for(path: Path) -> str:
    """Map a file suffix to the artefact kind the interface previews."""
    return ARTEFACT_KIND_BY_SUFFIX.get(path.suffix.lower(), "text")


def announce_artefact(
    context: ToolContext, canonical_path: Path, preview_path: Path | None = None
) -> None:
    """Record a created or changed file and tell the interface about it."""
    workspace = context.allowlist.workspace
    is_in_workspace = context.allowlist.is_inside_workspace(canonical_path)
    relative_path = (
        canonical_path.relative_to(workspace).as_posix()
        if is_in_workspace
        else str(canonical_path)
    )
    context.changed_paths.add(relative_path)
    kind = artefact_kind_for(canonical_path)
    context.services.store.record_artefact(
        context.session_id, relative_path, kind, context.model_id
    )
    context.emit(
        AgentEvent(
            EventType.ARTEFACT,
            {
                "relative_path": relative_path,
                "kind": kind,
                "preview_path": (
                    preview_path.relative_to(workspace).as_posix()
                    if preview_path
                    else None
                ),
            },
        )
    )


def _read_text(canonical_path: Path) -> str:
    if canonical_path.suffix.lower() in BINARY_DOCUMENT_SUFFIXES:
        raise ToolExecutionError(
            f"{canonical_path.suffix} is a binary document. To read or analyse its "
            "content call extract_from_document with this path and an instruction"
        )
    try:
        return canonical_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ToolExecutionError(f"file not found: {canonical_path.name}") from exc
    except IsADirectoryError as exc:
        raise ToolExecutionError("that path is a folder; use list_dir") from exc
    except PermissionError as exc:
        raise ToolExecutionError("that path cannot be read as a file") from exc


async def read_file(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Return a numbered range of lines from a text file."""
    canonical_path = context.allowlist.resolve_allowed(arguments["path"])
    lines = _read_text(canonical_path).splitlines()
    start_line = max(1, int(arguments.get("start_line", 1)))
    line_count = int(arguments.get("line_count", DEFAULT_READ_LINES))
    selected = lines[start_line - 1 : start_line - 1 + line_count]
    numbered = "\n".join(
        f"{number}: {line}" for number, line in enumerate(selected, start=start_line)
    )
    footer = (
        f"\n[showing lines {start_line}-{start_line + len(selected) - 1} "
        f"of {len(lines)}]"
    )
    return ToolOutput(numbered + footer, file_reference=arguments["path"])


async def list_dir(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """List a folder's entries with sizes."""
    canonical_path = context.allowlist.resolve_allowed(arguments.get("path", "."))
    if not canonical_path.is_dir():
        raise ToolExecutionError("that path is not a folder")
    entries = sorted(canonical_path.iterdir(), key=lambda entry: entry.name.lower())
    lines = [
        f"{entry.name}/"
        if entry.is_dir()
        else f"{entry.name} ({entry.stat().st_size} bytes)"
        for entry in entries[:MAX_LISTED_ENTRIES]
    ]
    if len(entries) > MAX_LISTED_ENTRIES:
        lines.append(f"[... {len(entries) - MAX_LISTED_ENTRIES} more entries]")
    return ToolOutput("\n".join(lines) or "(empty folder)")


async def search_files(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Find lines containing a phrase in text files under a folder."""
    root = context.allowlist.resolve_allowed(arguments.get("path", "."))
    phrase = str(arguments["query"]).lower()
    name_pattern = arguments.get("name_pattern", "*")
    matches: list[str] = []
    for candidate in sorted(root.rglob("*")):
        if len(matches) >= MAX_SEARCH_MATCHES:
            break
        if not _is_searchable(candidate, name_pattern):
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if phrase in line.lower():
                relative = candidate.relative_to(root).as_posix()
                matches.append(f"{relative}:{line_number}: {line.strip()[:200]}")
                if len(matches) >= MAX_SEARCH_MATCHES:
                    break
    return ToolOutput("\n".join(matches) or "No matches.")


def _is_searchable(candidate: Path, name_pattern: str) -> bool:
    return (
        candidate.is_file()
        and TO_DELETE_FOLDER_NAME not in candidate.parts
        and candidate.suffix.lower() not in BINARY_DOCUMENT_SUFFIXES
        and fnmatch.fnmatch(candidate.name, name_pattern)
        and candidate.stat().st_size <= MAX_SEARCHED_FILE_BYTES
    )


async def write_file(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Create or replace a text file."""
    canonical_path = context.allowlist.resolve_allowed(arguments["path"])
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(arguments["content"], encoding="utf-8")
    announce_artefact(context, canonical_path)
    return ToolOutput(
        f"Wrote {len(arguments['content'])} characters to {arguments['path']}."
    )


async def edit_file(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Replace one exact occurrence of a passage in a text file."""
    canonical_path = context.allowlist.resolve_allowed(arguments["path"])
    original_text = _read_text(canonical_path)
    occurrence_count = original_text.count(arguments["old_text"])
    if occurrence_count != 1:
        raise ToolExecutionError(
            f"old_text must appear exactly once; it appears {occurrence_count} "
            "times. Read the file and copy the passage exactly"
        )
    canonical_path.write_text(
        original_text.replace(arguments["old_text"], arguments["new_text"]),
        encoding="utf-8",
    )
    announce_artefact(context, canonical_path)
    return ToolOutput(f"Edited {arguments['path']}.")


async def remove_file(context: ToolContext, arguments: dict[str, Any]) -> ToolOutput:
    """Move a file into `_to_delete` beside it. Nothing is erased."""
    canonical_path = context.allowlist.resolve_allowed(arguments["path"])
    if not canonical_path.is_file():
        raise ToolExecutionError("file not found")
    holding_folder = canonical_path.parent / TO_DELETE_FOLDER_NAME
    holding_folder.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    destination = holding_folder / f"{timestamp}-{canonical_path.name}"
    shutil.move(str(canonical_path), destination)
    return ToolOutput(
        f"Moved {arguments['path']} to {TO_DELETE_FOLDER_NAME}/. It has not "
        "been erased; the user can restore or delete it."
    )


_PATH_PROPERTY = {
    "type": "string",
    "description": "File path. Relative paths are inside the session workspace.",
}


def register_file_tools(registry: ToolRegistry) -> None:
    """Register every file tool."""
    registry.register(
        ToolDefinition(
            name="read_file",
            description=(
                "Read lines from a text file and return them with line numbers. "
                "Use start_line and line_count to page through a long file."
            ),
            parameters=object_schema(
                {
                    "path": _PATH_PROPERTY,
                    "start_line": {"type": "integer", "minimum": 1},
                    "line_count": {"type": "integer", "minimum": 1, "maximum": 400},
                },
                ["path"],
            ),
            tier=ToolTier.READ,
            handler=read_file,
            target_argument="path",
        )
    )
    registry.register(
        ToolDefinition(
            name="list_dir",
            description=(
                "List the files and folders inside a folder. "
                "Call with no path to list the session workspace."
            ),
            parameters=object_schema({"path": _PATH_PROPERTY}, []),
            tier=ToolTier.READ,
            handler=list_dir,
            target_argument="path",
        )
    )
    registry.register(
        ToolDefinition(
            name="search_files",
            description=(
                "Search text files under a folder for an exact phrase and return "
                "matching lines. Use it to locate a file before reading it."
            ),
            parameters=object_schema(
                {
                    "query": {"type": "string", "minLength": 2},
                    "path": _PATH_PROPERTY,
                    "name_pattern": {
                        "type": "string",
                        "description": "Glob on the file name, such as *.md",
                    },
                },
                ["query"],
            ),
            tier=ToolTier.READ,
            handler=search_files,
            target_argument="path",
        )
    )
    registry.register(
        ToolDefinition(
            name="write_file",
            description=(
                "Create a text file, or replace it completely if it exists. "
                "Use it for markdown, HTML, SVG, CSV and other plain text."
            ),
            parameters=object_schema(
                {"path": _PATH_PROPERTY, "content": {"type": "string"}},
                ["path", "content"],
            ),
            tier=ToolTier.WRITE,
            handler=write_file,
            target_argument="path",
        )
    )
    registry.register(
        ToolDefinition(
            name="edit_file",
            description=(
                "Replace one exact passage in an existing text file. "
                "old_text must match the file exactly and appear only once."
            ),
            parameters=object_schema(
                {
                    "path": _PATH_PROPERTY,
                    "old_text": {"type": "string", "minLength": 1},
                    "new_text": {"type": "string"},
                },
                ["path", "old_text", "new_text"],
            ),
            tier=ToolTier.WRITE,
            handler=edit_file,
            target_argument="path",
        )
    )
    registry.register(
        ToolDefinition(
            name="remove_file",
            description=(
                "Remove a file by moving it into a _to_delete folder. "
                "The file is not erased and the user must approve every call."
            ),
            parameters=object_schema({"path": _PATH_PROPERTY}, ["path"]),
            tier=ToolTier.EXTERNAL,
            handler=remove_file,
            target_argument="path",
            keywords=("delete", "erase", "remove", "trash"),
        )
    )
