"""Named skills load deterministically; long documents are read in full."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.bootstrap import Application
from orchestrator.events import AgentEvent, EventType
from orchestrator.knowledge.chunking import chunk_markdown, split_text_windows
from orchestrator.skills import SkillIndex
from orchestrator.tests.conftest import ScriptedGateway, text_reply, tool_call_reply
from orchestrator.toolkit import extraction
from orchestrator.toolkit.context import ToolContext

REPOSITORY_SKILLS = Path(__file__).resolve().parents[2] / "skills"


def _long_transcript(sentence_count: int) -> str:
    return " ".join(
        f"Sentence {number} of the transcript." for number in range(sentence_count)
    )


def test_windows_cover_every_character_of_one_huge_paragraph() -> None:
    text = _long_transcript(3000)

    windows = split_text_windows(text, 10_000, 400)

    assert len(windows) > 1
    assert windows[0].startswith("Sentence 0 ")
    assert windows[-1].endswith("Sentence 2999 of the transcript.")
    for earlier, later in zip(windows, windows[1:], strict=False):
        assert later[:50] in earlier, "consecutive windows must overlap"


def test_chunking_no_longer_drops_the_tail_of_a_huge_paragraph() -> None:
    text = "# Transcript\n\n" + _long_transcript(3000)

    chunks = chunk_markdown(text)

    assert "Sentence 2999 of the transcript." in chunks[-1].text
    assert sum(len(chunk.text) for chunk in chunks) >= len(_long_transcript(3000))


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "using you meeting-action skill find actions in this transcript",
            ["meeting-actions"],
        ),
        ("/meeting-actions please", ["meeting-actions"]),
        ("Use the slide deck skill for this", ["slide-deck"]),
        ("make me a spreadsheet of costs", []),
        ("what is a meeting action?", []),
    ],
)
def test_skills_are_found_when_named_with_the_word_skill_or_a_slash(
    message: str, expected: list[str]
) -> None:
    skills = SkillIndex(REPOSITORY_SKILLS)

    assert [skill.name for skill in skills.find_referenced(message)] == expected


def test_skill_front_matter_declares_allowed_tools() -> None:
    skill = SkillIndex(REPOSITORY_SKILLS).get("meeting-actions")

    assert skill.allowed_tools == ("extract_from_document", "write_file")


async def test_named_skill_is_loaded_before_the_model_runs_and_only_once(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    scripted_gateway.replies = [text_reply("Ready."), text_reply("Still ready.")]

    await application.agent_loop.run_turn(tool_context, "use the meeting-action skill")
    await application.agent_loop.run_turn(
        tool_context, "again with the meeting-action skill"
    )

    first_request = scripted_gateway.chat_requests[0]["messages"]
    skill_result = first_request[-1]
    assert skill_result["role"] == "tool"
    assert "extract_from_document" in skill_result["content"]
    harness_call = first_request[-2]
    assert harness_call["tool_calls"][0]["function"]["name"] == "load_skill"
    load_events = [
        event
        for event in emitted_events
        if event.type == EventType.TOOL_CALL
        and event.payload["tool_name"] == "load_skill"
    ]
    assert len(load_events) == 1
    stored = application.services.store.load_messages(tool_context.session_id)
    assert stored[1]["model_id"] == "harness"


async def test_loading_a_skill_makes_its_allowed_tools_callable(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
) -> None:
    scripted_gateway.replies = [
        tool_call_reply("load_skill", {"name": "slide-deck"}),
        text_reply("ok"),
    ]

    await application.agent_loop.run_turn(tool_context, "make some slides")

    second_tools = {
        tool["function"]["name"] for tool in scripted_gateway.chat_requests[1]["tools"]
    }
    assert "build_pptx" in second_tools


async def test_unknown_allowed_tool_is_skipped_rather_than_failing_the_turn(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
) -> None:
    tool_context.discovered_tool_names.add("connector_that_failed_to_start")
    scripted_gateway.replies = [text_reply("fine")]

    assert await application.agent_loop.run_turn(tool_context, "hello") == "answered"


async def test_extraction_reads_every_part_and_reports_coverage(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extraction, "PART_TOKENS", 1000)
    monkeypatch.setattr(extraction, "PART_OVERLAP_TOKENS", 20)
    (tool_context.allowlist.workspace / "transcript.md").write_text(
        _long_transcript(300)
    )
    part_count = len(split_text_windows(_long_transcript(300), 4000, 80))
    scripted_gateway.replies = (
        [text_reply("- Tom: draft the plan")]
        + [text_reply("NONE")] * (part_count - 2)
        + [text_reply("- Dana: confirm retention")]
    )

    outcome = await application.router.execute(
        tool_context,
        "c1",
        "extract_from_document",
        json.dumps({"path": "transcript.md", "instruction": "list every action"}),
    )

    assert f"Read all {part_count} parts" in outcome.text
    assert "Tom: draft the plan" in outcome.text
    assert "Dana: confirm retention" in outcome.text
    assert "NONE" not in outcome.text
    utility_calls = [
        request
        for request in scripted_gateway.chat_requests
        if request["role"] == "utility"
    ]
    assert len(utility_calls) == part_count
    assert "<document_part" in utility_calls[0]["messages"][1]["content"]


async def test_extraction_refuses_documents_beyond_the_part_limit(
    application: Application,
    tool_context: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extraction, "PART_TOKENS", 100)
    monkeypatch.setattr(extraction, "MAX_PARTS", 2)
    (tool_context.allowlist.workspace / "long.md").write_text(_long_transcript(500))

    outcome = await application.router.execute(
        tool_context,
        "c1",
        "extract_from_document",
        json.dumps({"path": "long.md", "instruction": "list every action"}),
    )

    assert outcome.outcome == "error"
    assert "too long" in outcome.text


async def test_read_document_says_when_it_shortens_a_paragraph(
    application: Application, tool_context: ToolContext
) -> None:
    import docx

    document = docx.Document()
    document.add_paragraph(_long_transcript(200))
    document.save(str(tool_context.allowlist.workspace / "notes.docx"))

    outcome = await application.router.execute(
        tool_context, "c1", "read_document", json.dumps({"path": "notes.docx"})
    )

    assert "more characters not shown" in outcome.text
    assert "extract_from_document" in outcome.text
