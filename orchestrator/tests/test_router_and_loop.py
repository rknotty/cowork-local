"""Tool router policy and the agent loop, against a scripted model."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orchestrator.bootstrap import Application
from orchestrator.events import AgentEvent, EventType
from orchestrator.tests.conftest import ScriptedGateway, text_reply, tool_call_reply
from orchestrator.toolkit.context import ToolContext


def _events_of(events: list[AgentEvent], event_type: EventType) -> list[AgentEvent]:
    return [event for event in events if event.type == event_type]


def _audit_records(application: Application) -> list[dict[str, object]]:
    lines = application.services.audit_log.path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


async def _answer_next_approval(
    context: ToolContext, events: list[AgentEvent], decision: str
) -> None:
    while not _events_of(events, EventType.APPROVAL_REQUEST):
        await asyncio.sleep(0)
    request = _events_of(events, EventType.APPROVAL_REQUEST)[-1]
    context.broker.resolve(str(request.payload["request_id"]), decision)


async def test_write_inside_workspace_needs_no_approval(
    application: Application,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    outcome = await application.router.execute(
        tool_context, "c1", "write_file", json.dumps({"path": "a.md", "content": "hi"})
    )

    assert outcome.outcome == "ok"
    assert (tool_context.allowlist.workspace / "a.md").read_text() == "hi"
    assert not _events_of(emitted_events, EventType.APPROVAL_REQUEST)
    assert (
        _events_of(emitted_events, EventType.ARTEFACT)[0].payload["kind"] == "markdown"
    )


async def test_write_to_connected_folder_waits_for_approval_and_respects_denial(
    application: Application,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
    tmp_path: Path,
) -> None:
    connected = tmp_path / "connected"
    connected.mkdir()
    application.services.connected_folders = [str(connected)]
    context = application.create_tool_context(
        tool_context.session_id, emitted_events.append
    )
    target = connected / "out.md"

    execution = asyncio.create_task(
        application.router.execute(
            context,
            "c1",
            "write_file",
            json.dumps({"path": str(target), "content": "x"}),
        )
    )
    await _answer_next_approval(context, emitted_events, "deny")
    outcome = await execution

    assert outcome.outcome == "denied"
    assert not target.exists()
    assert _audit_records(application)[-1]["approval_decision"] == "deny"


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("read_file", {"path": "C:\\Users"}),
        ("list_dir", {"path": "C:\\Users"}),
        ("write_file", {"path": "..\\..\\escape.txt", "content": "x"}),
        ("remove_file", {"path": "C:\\Windows\\win.ini"}),
    ],
)
async def test_paths_outside_allowed_folders_are_refused_and_logged(
    application: Application,
    tool_context: ToolContext,
    tool_name: str,
    arguments: dict[str, str],
) -> None:
    if tool_name == "remove_file":
        # Tier 3 asks first; the refusal must still hold after an approval.
        execution = asyncio.create_task(
            application.router.execute(
                tool_context, "c1", tool_name, json.dumps(arguments)
            )
        )
        events: list[AgentEvent] = []
        tool_context.emit = events.append
        await asyncio.sleep(0)
        for request_id in list(tool_context.broker._pending):
            tool_context.broker.resolve(request_id, "allow_once")
        outcome = await execution
    else:
        outcome = await application.router.execute(
            tool_context, "c1", tool_name, json.dumps(arguments)
        )

    assert outcome.outcome == "error"
    last_record = _audit_records(application)[-1]
    assert last_record["error_code"] == "PATH_NOT_ALLOWED"
    assert last_record["tool_name"] == tool_name


async def test_tier_three_ignores_session_approval(
    application: Application,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    for name in ("one.txt", "two.txt"):
        (tool_context.allowlist.workspace / name).write_text("x")
    for name in ("one.txt", "two.txt"):
        execution = asyncio.create_task(
            application.router.execute(
                tool_context, name, "remove_file", json.dumps({"path": name})
            )
        )
        approvals_before = len(_events_of(emitted_events, EventType.APPROVAL_REQUEST))
        while (
            len(_events_of(emitted_events, EventType.APPROVAL_REQUEST))
            == approvals_before
        ):
            await asyncio.sleep(0)
        await _answer_next_approval(tool_context, emitted_events, "allow_session")
        assert (await execution).outcome == "ok"

    assert len(_events_of(emitted_events, EventType.APPROVAL_REQUEST)) == 2
    assert (tool_context.allowlist.workspace / "_to_delete").is_dir()


async def test_remove_file_moves_rather_than_erases(
    application: Application,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    (tool_context.allowlist.workspace / "old.txt").write_text("keep me")
    execution = asyncio.create_task(
        application.router.execute(
            tool_context, "c1", "remove_file", json.dumps({"path": "old.txt"})
        )
    )
    await _answer_next_approval(tool_context, emitted_events, "allow_once")
    await execution

    held_files = list((tool_context.allowlist.workspace / "_to_delete").iterdir())
    assert len(held_files) == 1
    assert held_files[0].read_text() == "keep me"


@pytest.mark.parametrize(
    ("tool_name", "arguments_json", "expected_fragment"),
    [
        ("no_such_tool", "{}", "Valid tools"),
        ("read_file", "{not json", "not valid JSON"),
        ("read_file", "{}", "'path' is a required property"),
        ("task_list", json.dumps({"action": "destroy"}), "is not one of"),
        ("read_file", json.dumps({"path": "a", "extra": 1}), "Additional properties"),
    ],
)
async def test_malformed_calls_return_a_repair_message(
    application: Application,
    tool_context: ToolContext,
    tool_name: str,
    arguments_json: str,
    expected_fragment: str,
) -> None:
    outcome = await application.router.execute(
        tool_context, "c1", tool_name, arguments_json
    )

    assert outcome.is_malformed_call
    assert expected_fragment in outcome.text


async def test_loop_runs_tool_then_answers(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    (tool_context.allowlist.workspace / "notes.txt").write_text("alpha\nbeta")
    scripted_gateway.replies = [
        tool_call_reply("read_file", {"path": "notes.txt"}),
        text_reply("The file has two lines."),
    ]

    reason = await application.agent_loop.run_turn(
        tool_context, "What is in notes.txt?"
    )

    assert reason == "answered"
    second_request_messages = scripted_gateway.chat_requests[1]["messages"]
    tool_message = second_request_messages[-1]
    assert tool_message["role"] == "tool"
    assert "<tool_output" in tool_message["content"]
    assert "1: alpha" in tool_message["content"]
    assert _events_of(emitted_events, EventType.DONE)[0].payload["reason"] == "answered"
    kinds = [record["kind"] for record in _audit_records(application)]
    assert kinds == ["model_call", "tool_call", "model_call"]
    assert application.services.audit_log.verify_chain() == 3


async def test_loop_stops_after_repeated_malformed_calls(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    scripted_gateway.replies = [tool_call_reply("read_file", "{broken")] * 5

    reason = await application.agent_loop.run_turn(tool_context, "read it")

    assert reason == "error"
    assert len(scripted_gateway.chat_requests) == 3
    error_event = _events_of(emitted_events, EventType.ERROR)[0]
    assert error_event.payload["error"] == "TOOL_CALLS_MALFORMED"


async def test_turn_duration_is_reported_and_stored_but_never_sent_to_the_model(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    scripted_gateway.replies = [text_reply("First."), text_reply("Second.")]

    await application.agent_loop.run_turn(tool_context, "one")
    await application.agent_loop.run_turn(tool_context, "two")

    done = _events_of(emitted_events, EventType.DONE)[0]
    assert isinstance(done.payload["duration_ms"], int)
    assert done.payload["duration_ms"] >= 0
    stored = application.services.store.load_messages(tool_context.session_id)
    assert "turn_duration_ms" in stored[1]
    second_request = scripted_gateway.chat_requests[1]["messages"]
    assert all(
        set(message) <= {"role", "content", "tool_calls", "tool_call_id"}
        for message in second_request
    )


async def test_loop_recovers_after_one_malformed_call(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
) -> None:
    scripted_gateway.replies = [
        tool_call_reply("list_dir", "{broken"),
        tool_call_reply("list_dir", {}),
        text_reply("The workspace is empty."),
    ]

    assert (
        await application.agent_loop.run_turn(tool_context, "list files") == "answered"
    )


async def test_loop_stops_at_the_step_limit(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
) -> None:
    max_steps = application.services.settings.max_steps
    scripted_gateway.replies = [
        tool_call_reply("search_files", {"query": f"term {step}"})
        for step in range(max_steps + 3)
    ]

    reason = await application.agent_loop.run_turn(tool_context, "loop forever")

    assert reason == "step_limit"
    assert len(scripted_gateway.chat_requests) == max_steps


async def test_identical_repeat_call_is_not_run_again_and_is_audited(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
) -> None:
    (tool_context.allowlist.workspace / "a.md").write_text("RAG: Green")
    scripted_gateway.replies = [
        tool_call_reply("read_file", {"path": "a.md"}),
        tool_call_reply("read_file", '{ "path" : "a.md" }'),
        text_reply("Green."),
    ]

    reason = await application.agent_loop.run_turn(tool_context, "status?")

    assert reason == "answered"
    tool_messages = [
        message
        for message in application.services.store.load_messages(tool_context.session_id)
        if message["role"] == "tool"
    ]
    assert "RAG: Green" in str(tool_messages[0]["content"])
    assert "already called read_file" in str(tool_messages[1]["content"])
    outcomes = [
        record["outcome"]
        for record in _audit_records(application)
        if record["kind"] == "tool_call"
    ]
    assert outcomes == ["ok", "repeated"]


async def test_loop_stops_when_the_model_only_repeats_itself(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
) -> None:
    scripted_gateway.replies = [tool_call_reply("list_dir", {})] * 8

    reason = await application.agent_loop.run_turn(tool_context, "list")

    assert reason == "error"
    assert len(scripted_gateway.chat_requests) == 4


async def test_blank_final_reply_is_reported_as_an_error_not_an_answer(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    scripted_gateway.replies = [text_reply("\n\n  ")]

    reason = await application.agent_loop.run_turn(tool_context, "hello")

    assert reason == "error"
    error_event = _events_of(emitted_events, EventType.ERROR)[0]
    assert error_event.payload["error"] == "MODEL_GAVE_NO_ANSWER"
    roles = [
        message["role"]
        for message in application.services.store.load_messages(tool_context.session_id)
    ]
    assert roles == ["user"]


async def test_find_tool_makes_a_deferred_tool_callable_next_step(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
) -> None:
    scripted_gateway.replies = [
        tool_call_reply("find_tool", {"query": "spreadsheet excel"}),
        text_reply("Found it."),
    ]

    await application.agent_loop.run_turn(tool_context, "I need a spreadsheet")

    first_tools = {
        tool["function"]["name"] for tool in scripted_gateway.chat_requests[0]["tools"]
    }
    second_tools = {
        tool["function"]["name"] for tool in scripted_gateway.chat_requests[1]["tools"]
    }
    assert "build_xlsx" not in first_tools
    assert "build_xlsx" in second_tools
    # Eleven core tools: one over the plan's guide, recorded in tools.yaml.
    assert len(first_tools) <= 11


async def test_task_list_emits_full_list_on_each_update(
    application: Application,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    await application.router.execute(
        tool_context,
        "c1",
        "task_list",
        json.dumps({"action": "create", "titles": ["Read", "Write"]}),
    )
    await application.router.execute(
        tool_context,
        "c2",
        "task_list",
        json.dumps({"action": "update", "task_id": 1, "status": "done"}),
    )

    last_update = _events_of(emitted_events, EventType.TASK_UPDATE)[-1]
    assert last_update.payload["tasks"] == [
        {"id": 1, "title": "Read", "status": "done"},
        {"id": 2, "title": "Write", "status": "pending"},
    ]


async def test_cancelled_turn_still_emits_done(
    application: Application,
    scripted_gateway: ScriptedGateway,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    scripted_gateway.replies = [
        tool_call_reply("ask_user", {"question": "Which file do you mean?"})
    ]
    turn = asyncio.create_task(application.agent_loop.run_turn(tool_context, "do it"))
    while not _events_of(emitted_events, EventType.QUESTION):
        await asyncio.sleep(0)
    turn.cancel()

    assert await turn == "cancelled"
    assert (
        _events_of(emitted_events, EventType.DONE)[0].payload["reason"] == "cancelled"
    )
