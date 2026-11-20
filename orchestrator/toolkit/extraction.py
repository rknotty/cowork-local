"""extract_from_document: read a document of any length, part by part.

A long transcript can exceed the model's whole context window, so it cannot
be read in one go. This tool splits the document into parts, has the utility
model extract what the instruction asks for from each part in a fresh
context, and returns only the merged findings. That is the plan's sequential
sub-task pattern (section 7, step 9): one GPU, so parts run one after another.

Every part is read in full; the result says how many parts that was, so a
reader can tell the whole document was covered.
"""

from __future__ import annotations

import asyncio
from typing import Any

from orchestrator.audit import AuditRecord, hash_content
from orchestrator.context_budget import CHARACTERS_PER_TOKEN, estimate_tokens
from orchestrator.errors import ToolExecutionError
from orchestrator.events import AgentEvent, EventType
from orchestrator.gateway import ChatResult
from orchestrator.knowledge.chunking import split_text_windows
from orchestrator.knowledge.parsing import parse_document
from orchestrator.prompt_builder import load_prompts
from orchestrator.toolkit.context import ToolContext
from orchestrator.toolkit.registry import (
    ToolDefinition,
    ToolOutput,
    ToolRegistry,
    ToolTier,
    object_schema,
)

UTILITY_ROLE = "utility"
# About 2,500 tokens per part: with the instruction and a 512-token answer it
# fits the utility model's window with a wide margin.
PART_TOKENS = 2500
PART_OVERLAP_TOKENS = 100
# About 240,000 characters. Beyond this a run would take many minutes; the
# user should narrow the request instead.
MAX_PARTS = 24
NOTHING_FOUND_MARKER = "NONE"


async def _ask_utility(
    context: ToolContext, system_prompt: str, user_content: str
) -> ChatResult:
    """One utility-model call, audited like every model call."""
    gateway = context.services.gateway
    result = await gateway.chat(
        UTILITY_ROLE,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    context.services.audit_log.append(
        AuditRecord(
            kind="model_call",
            session_id=context.session_id,
            model_id=result.model_id,
            role=UTILITY_ROLE,
            input_hash=hash_content(user_content),
            result_hash=hash_content(result.text),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            duration_ms=result.duration_ms,
        )
    )
    return result


def _report_progress(context: ToolContext, part_number: int, part_count: int) -> None:
    """Show progress in the task panel: a 20-part read takes minutes."""
    context.emit(
        AgentEvent(
            EventType.TASK_UPDATE,
            {
                "tasks": [
                    *(
                        {"id": task.id, "title": task.title, "status": task.status}
                        for task in context.tasks
                    ),
                    {
                        "id": 0,
                        "title": f"Reading document part {part_number} of {part_count}",
                        "status": "in_progress" if part_number < part_count else "done",
                    },
                ]
            },
        )
    )


async def extract_from_document(
    context: ToolContext, arguments: dict[str, Any]
) -> ToolOutput:
    """Extract what the instruction asks for from every part of a document."""
    canonical_path = context.allowlist.resolve_allowed(arguments["path"])
    if not canonical_path.is_file():
        raise ToolExecutionError(f"file not found: {arguments['path']}")
    text = await asyncio.to_thread(parse_document, canonical_path)
    if not text.strip():
        raise ToolExecutionError("the document has no readable text")
    parts = split_text_windows(
        text,
        PART_TOKENS * CHARACTERS_PER_TOKEN,
        PART_OVERLAP_TOKENS * CHARACTERS_PER_TOKEN,
    )
    if len(parts) > MAX_PARTS:
        raise ToolExecutionError(
            f"the document is too long to read in one request ({len(parts)} parts, "
            f"limit {MAX_PARTS}). Ask the user which section to use"
        )
    prompts = load_prompts(context.services.settings.repository_root)
    instruction = arguments["instruction"]
    findings: list[str] = []
    for part_number, part in enumerate(parts, start=1):
        _report_progress(context, part_number, len(parts))
        result = await _ask_utility(
            context,
            prompts["extract_instruction"].format(instruction=instruction),
            f'<document_part number="{part_number}" of="{len(parts)}">\n{part}\n</document_part>',
        )
        answer = result.text.strip()
        if answer and answer.upper().rstrip(".") != NOTHING_FOUND_MARKER:
            findings.append(answer)
    merged = await _merge_findings(
        context, prompts["merge_instruction"], instruction, findings
    )
    return ToolOutput(
        f"Read all {len(parts)} parts of {arguments['path']} "
        f"({len(text):,} characters).\n\n{merged}"
    )


async def _merge_findings(
    context: ToolContext, merge_prompt: str, instruction: str, findings: list[str]
) -> str:
    """Combine per-part findings, merging only when they would not fit."""
    if not findings:
        return "Nothing matching the instruction was found anywhere in the document."
    combined = "\n\n".join(findings)
    budget_tokens = int(context.services.settings.tool_result_max_tokens * 0.9)
    if len(findings) == 1 or estimate_tokens(combined) <= budget_tokens:
        return combined
    result = await _ask_utility(
        context, merge_prompt.format(instruction=instruction), combined
    )
    return result.text.strip() or combined


def register_extraction_tool(registry: ToolRegistry) -> None:
    """Register extract_from_document."""
    registry.register(
        ToolDefinition(
            name="extract_from_document",
            description=(
                "Read a whole document of any length, such as a long transcript, and "
                "extract what the instruction asks for. Use this instead of read_file "
                "or read_document for summaries, actions or facts from a long file."
            ),
            parameters=object_schema(
                {
                    "path": {"type": "string"},
                    "instruction": {
                        "type": "string",
                        "minLength": 5,
                        "description": "What to extract, for example: list every action with its owner and due date",
                    },
                },
                ["path", "instruction"],
            ),
            tier=ToolTier.READ,
            handler=extract_from_document,
            target_argument="path",
            keywords=(
                "transcript",
                "summarise",
                "extract",
                "actions",
                "long",
                "document",
                "meeting",
            ),
        )
    )
