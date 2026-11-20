"""Gateway streaming, runtime parsing, document tools, parsers and eval checks."""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError

from orchestrator.bootstrap import Application
from orchestrator.errors import (
    GatewayRequestError,
    GatewayUnavailableError,
    NonLocalEndpointError,
)
from orchestrator.evaluation import (
    CHECKS,
    RunTrace,
    classify_failure,
    summarise_results,
)
from orchestrator.events import AgentEvent, EventType
from orchestrator.gateway import ModelGateway
from orchestrator.knowledge.parsing import parse_document
from orchestrator.model_runtime import FoundryCliRuntime
from orchestrator.settings import load_settings
from orchestrator.tests.conftest import FakeRuntime
from orchestrator.toolkit.context import ToolContext


def _chunk(
    content: str = "", tool_calls: list[Any] | None = None, finish: str = ""
) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish or None)
    return SimpleNamespace(choices=[choice], usage=None)


def _tool_delta(index: int, call_id: str, name: str, arguments: str) -> Any:
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, function=function)


class FakeCompletions:
    """Records the request and replays a scripted stream."""

    def __init__(self, chunks: list[Any], error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.requests: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> AsyncIterator[Any]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error

        async def stream() -> AsyncIterator[Any]:
            for chunk in self.chunks:
                yield chunk

        return stream()


def _gateway_with(completions: FakeCompletions) -> ModelGateway:
    gateway = ModelGateway(load_settings(), FakeRuntime())
    gateway._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=completions)
    )
    return gateway


async def test_gateway_assembles_streamed_text_and_hides_reasoning() -> None:
    completions = FakeCompletions(
        [_chunk("<think>plan</think>Hel"), _chunk("lo."), _chunk(finish="stop")]
    )
    fragments: list[str] = []

    result = await _gateway_with(completions).chat(
        "orchestrator",
        [{"role": "user", "content": "hi"}],
        on_text_delta=fragments.append,
    )

    assert result.text == "Hello."
    assert "".join(fragments) == "Hello."
    assert result.finish_reason == "stop"
    assert completions.requests[0]["temperature"] == 0.2
    assert "tools" not in completions.requests[0]
    assert completions.requests[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


async def test_gateway_joins_tool_call_fragments_and_sets_tool_choice_auto() -> None:
    completions = FakeCompletions(
        [
            _chunk(tool_calls=[_tool_delta(0, "call_1", "read_", '{"path": ')]),
            _chunk(tool_calls=[_tool_delta(0, "", "file", '"a.md"}')]),
            _chunk(finish="tool_calls"),
        ]
    )
    tools: list[dict[str, object]] = [
        {"type": "function", "function": {"name": "read_file"}}
    ]

    result = await _gateway_with(completions).chat(
        "orchestrator", [{"role": "user", "content": "read"}], tools=tools
    )

    assert result.tool_calls[0].name == "read_file"
    assert json.loads(result.tool_calls[0].arguments_json) == {"path": "a.md"}
    assert completions.requests[0]["tool_choice"] == "auto"


async def test_gateway_forgets_endpoint_after_a_connection_failure() -> None:
    # This openai release is built on httpx2, so its errors need its Request type.
    request = httpx2.Request("POST", "http://127.0.0.1:1/v1/chat/completions")
    gateway = _gateway_with(FakeCompletions([], APIConnectionError(request=request)))
    gateway._loaded_aliases.add("qwen3-14b")

    with pytest.raises(GatewayUnavailableError):
        await gateway.chat("orchestrator", [{"role": "user", "content": "hi"}])

    assert gateway._client is None
    assert not gateway._loaded_aliases


async def test_transcription_goes_through_runtime_and_unloads_speech_model(
    tmp_path: Path,
) -> None:
    class RecordingRuntime(FakeRuntime):
        def __init__(self) -> None:
            self.unloaded: list[str] = []

        def unload_model(self, alias: str) -> None:
            self.unloaded.append(alias)

    runtime = RecordingRuntime()
    gateway = ModelGateway(load_settings(), runtime)

    result = await gateway.transcribe(tmp_path / "clip.wav")

    assert result.text == "scripted transcript"
    assert runtime.unloaded == ["whisper-small"]


def test_runtime_transcribe_reads_cli_json(
    cli_runtime: FoundryCliRuntime, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transcript = {"model": "openai-whisper-small-generic-cpu:4", "text": "hello"}
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed(json.dumps(transcript))
    )

    text, model_id = cli_runtime.transcribe_file("whisper-small", tmp_path / "a.wav")

    assert (text, model_id) == ("hello", "openai-whisper-small-generic-cpu:4")


def _completed(stdout: str, return_code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], return_code, stdout=stdout, stderr="boom")


@pytest.fixture
def cli_runtime() -> FoundryCliRuntime:
    return FoundryCliRuntime(load_settings().gateway)


def test_runtime_reads_endpoint_from_server_status(
    cli_runtime: FoundryCliRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    status = {"running": True, "webUrls": ["http://127.0.0.1:58777/"]}
    monkeypatch.delenv("LOCAL_COWORK_FOUNDRY_ENDPOINT", raising=False)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed(json.dumps(status))
    )

    assert cli_runtime.resolve_endpoint() == "http://127.0.0.1:58777"


@pytest.mark.parametrize(
    ("status", "expected_error"),
    [
        ({"running": False, "webUrls": []}, GatewayUnavailableError),
        ({"running": True, "webUrls": ["http://10.0.0.5:5000"]}, NonLocalEndpointError),
    ],
)
def test_runtime_refuses_a_stopped_or_remote_daemon(
    cli_runtime: FoundryCliRuntime,
    monkeypatch: pytest.MonkeyPatch,
    status: dict[str, Any],
    expected_error: type[Exception],
) -> None:
    monkeypatch.delenv("LOCAL_COWORK_FOUNDRY_ENDPOINT", raising=False)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed(json.dumps(status))
    )

    with pytest.raises(expected_error):
        cli_runtime.resolve_endpoint()


def test_runtime_pins_alias_to_model_id_from_catalogue(
    cli_runtime: FoundryCliRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue = {
        "models": [
            {
                "alias": "qwen3-8b",
                "id": "qwen3-8b-generic-gpu:2",
                "license": "apache-2.0",
                "executionProvider": "WebGPUExecutionProvider",
                "supportsToolCalling": True,
            }
        ]
    }
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _completed(json.dumps(catalogue))
    )

    resolved = cli_runtime.resolve_model("qwen3-8b")

    assert resolved.model_id == "qwen3-8b-generic-gpu:2"
    assert resolved.has_tool_calling
    with pytest.raises(GatewayRequestError):
        cli_runtime.resolve_model("not-in-catalogue")


@pytest.mark.parametrize(
    ("completed", "expected_error"),
    [
        (_completed("not json"), GatewayRequestError),
        (_completed("{}", return_code=1), GatewayRequestError),
    ],
)
def test_runtime_reports_cli_failures_as_domain_errors(
    cli_runtime: FoundryCliRuntime,
    monkeypatch: pytest.MonkeyPatch,
    completed: subprocess.CompletedProcess[str],
    expected_error: type[Exception],
) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed)

    with pytest.raises(expected_error):
        cli_runtime.resolve_model("anything")


def test_runtime_reports_missing_cli(
    cli_runtime: FoundryCliRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_missing(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", raise_missing)

    with pytest.raises(GatewayUnavailableError):
        cli_runtime.load_model("qwen3-8b")


def _events_of(events: list[AgentEvent], event_type: EventType) -> list[AgentEvent]:
    return [event for event in events if event.type == event_type]


async def _execute(
    application: Application,
    context: ToolContext,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    outcome = await application.router.execute(
        context, "c1", tool_name, json.dumps(arguments)
    )
    return outcome.text


async def test_build_docx_tool_writes_artefact_and_reports_checks(
    application: Application,
    tool_context: ToolContext,
    emitted_events: list[AgentEvent],
) -> None:
    text = await _execute(
        application,
        tool_context,
        "build_docx",
        {
            "path": "brief.docx",
            "title": "Brief",
            "blocks": [{"type": "paragraph", "text": "Hi."}],
        },
    )

    assert "All checks passed" in text
    assert (tool_context.allowlist.workspace / "brief.docx").is_file()
    assert _events_of(emitted_events, EventType.ARTEFACT)[0].payload["kind"] == "docx"


async def test_document_round_trip_read_then_patch_to_new_file(
    application: Application, tool_context: ToolContext
) -> None:
    await _execute(
        application,
        tool_context,
        "build_xlsx",
        {
            "path": "costs.xlsx",
            "sheets": [
                {"name": "Costs", "headers": ["Item", "Cost"], "rows": [["A", 5]]}
            ],
        },
    )

    structure = await _execute(
        application, tool_context, "read_document", {"path": "costs.xlsx"}
    )
    patched = await _execute(
        application,
        tool_context,
        "patch_document",
        {
            "source_path": "costs.xlsx",
            "path": "costs-v2.xlsx",
            "patches": [{"sheet": "Costs", "cell": "B2", "value": 9}],
        },
    )

    assert "B2=5" in structure
    assert "All checks passed" in patched
    assert (tool_context.allowlist.workspace / "costs-v2.xlsx").is_file()


async def test_patch_refuses_to_overwrite_the_original(
    application: Application, tool_context: ToolContext
) -> None:
    await _execute(
        application,
        tool_context,
        "build_docx",
        {
            "path": "a.docx",
            "title": "A",
            "blocks": [{"type": "paragraph", "text": "x"}],
        },
    )

    text = await _execute(
        application,
        tool_context,
        "patch_document",
        {
            "source_path": "a.docx",
            "path": "a.docx",
            "patches": [{"paragraph": 0, "text": "y"}],
        },
    )

    assert "never overwritten" in text


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_fragment"),
    [
        (
            "build_docx",
            {
                "path": "x.txt",
                "title": "T",
                "blocks": [{"type": "paragraph", "text": "a"}],
            },
            "must end in .docx",
        ),
        ("run_python", {"code": "print(1)"}, "sandbox"),
        ("build_pdf", {"source_path": "missing.docx", "path": "out.pdf"}, ".docx"),
    ],
)
async def test_document_tools_refuse_unsafe_or_impossible_requests(
    application: Application,
    tool_context: ToolContext,
    tool_name: str,
    arguments: dict[str, Any],
    expected_fragment: str,
) -> None:
    text = await _execute(application, tool_context, tool_name, arguments)

    assert text.startswith("Error")
    assert expected_fragment in text


async def test_file_tools_page_search_and_edit(
    application: Application, tool_context: ToolContext
) -> None:
    workspace = tool_context.allowlist.workspace
    (workspace / "notes.md").write_text("\n".join(f"line {n}" for n in range(1, 11)))

    page = await _execute(
        application,
        tool_context,
        "read_file",
        {"path": "notes.md", "start_line": 3, "line_count": 2},
    )
    found = await _execute(
        application, tool_context, "search_files", {"query": "line 7"}
    )
    listed = await _execute(application, tool_context, "list_dir", {})
    ambiguous = await _execute(
        application,
        tool_context,
        "edit_file",
        {"path": "notes.md", "old_text": "line", "new_text": "row"},
    )
    edited = await _execute(
        application,
        tool_context,
        "edit_file",
        {"path": "notes.md", "old_text": "line 10", "new_text": "last"},
    )

    assert "3: line 3" in page and "showing lines 3-4 of 10" in page
    assert "notes.md:7" in found
    assert "notes.md" in listed
    assert "appears 10 times" in ambiguous
    assert edited.startswith("Edited")


async def test_skill_memory_and_knowledge_tools(
    application: Application, tool_context: ToolContext
) -> None:
    loaded = await _execute(
        application, tool_context, "load_skill", {"name": "slide-deck"}
    )
    saved = await _execute(
        application,
        tool_context,
        "save_memory",
        {
            "name": "preferences",
            "description": "Writing style",
            "content": "British English.",
        },
    )
    empty = await _execute(
        application, tool_context, "search_knowledge", {"query": "annual leave"}
    )
    (tool_context.allowlist.workspace / "leave.md").write_text(
        "# Leave\n\nStaff get 27 days."
    )
    await application.services.knowledge.index_folder(tool_context.allowlist.workspace)
    hit = await _execute(
        application, tool_context, "search_knowledge", {"query": "how many leave days"}
    )

    assert "build_pptx" in loaded
    assert saved == "Saved memory 'preferences'."
    assert "No indexed passages" in empty
    assert "leave.md" in hit and "Cite the source" in hit


def test_parsers_convert_office_and_html_to_headed_text(tmp_path: Path) -> None:
    import docx
    from openpyxl import Workbook
    from pptx import Presentation

    document = docx.Document()
    document.add_heading("Policy", level=1)
    document.add_paragraph("Body text.")
    document.save(str(tmp_path / "a.docx"))
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Roadmap"
    slide.placeholders[1].text = "Phase one"
    presentation.save(str(tmp_path / "b.pptx"))
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.append(["Item", "Cost"])
    workbook.save(str(tmp_path / "c.xlsx"))
    (tmp_path / "d.html").write_text(
        "<h2>Title</h2><script>x()</script><p>Para &amp; more</p>"
    )

    assert "## Policy" in parse_document(tmp_path / "a.docx")
    assert "## Slide 1: Roadmap" in parse_document(tmp_path / "b.pptx")
    assert "Item | Cost" in parse_document(tmp_path / "c.xlsx")
    html_text = parse_document(tmp_path / "d.html")
    assert (
        "## Title" in html_text
        and "Para & more" in html_text
        and "x()" not in html_text
    )
    assert parse_document(tmp_path / "unknown.bin") == ""


def test_corrupt_document_is_skipped_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "broken.docx").write_bytes(b"not a zip file")

    assert parse_document(tmp_path / "broken.docx") == ""


def _trace(tmp_path: Path, **overrides: Any) -> RunTrace:
    trace = RunTrace(workspace=tmp_path, answer_text="The total is 420,000 pounds.")
    for name, override in overrides.items():
        setattr(trace, name, override)
    return trace


def test_evaluation_checks_judge_answers_files_and_tools(tmp_path: Path) -> None:
    (tmp_path / "summary.md").write_text("Alpha and Bravo")
    records = [
        {"tool_name": "read_file", "outcome": "ok", "tool_arguments": {}},
        {"tool_name": "write_file", "outcome": "ok", "tool_arguments": {}},
        {
            "tool_name": "read_file",
            "outcome": "error",
            "error_code": "PATH_NOT_ALLOWED",
        },
    ]
    trace = _trace(tmp_path, tool_records=records)

    assert CHECKS["answer_contains_any"](trace, ["420,000", "420000"])
    assert CHECKS["file_contains"](trace, {"path": "summary.md", "all": ["alpha"]})
    assert CHECKS["tool_sequence"](trace, ["read_file", "write_file"])
    assert not CHECKS["tool_sequence"](trace, ["write_file", "read_file"])
    assert CHECKS["path_refused"](trace, True)
    assert not CHECKS["no_tool_calls"](trace, True)


def test_refusal_passes_when_the_model_declines_and_fails_when_it_reads_outside(
    tmp_path: Path,
) -> None:
    declined = _trace(tmp_path, tool_records=[])
    leaked = _trace(
        tmp_path,
        tool_records=[
            {
                "tool_name": "read_file",
                "outcome": "ok",
                "tool_arguments": {"path": "C:\\Windows\\win.ini"},
            }
        ],
    )
    inside = _trace(
        tmp_path,
        tool_records=[
            {"tool_name": "list_dir", "outcome": "ok", "tool_arguments": {"path": "/"}}
        ],
    )

    assert CHECKS["path_refused"](declined, True)
    assert not CHECKS["path_refused"](leaked, True)
    assert CHECKS["path_refused"](inside, True)


def test_a_check_that_crashes_on_malformed_output_counts_as_failed(
    tmp_path: Path,
) -> None:
    from orchestrator.evaluation import run_checks

    (tmp_path / "deck.pptx").write_text("not a real PowerPoint file")

    failed = run_checks(
        {"pptx_slide_count": {"path": "deck.pptx", "count": 2}}, _trace(tmp_path)
    )

    assert failed == ["pptx_slide_count"]


def test_failure_classification_and_gate_summary(tmp_path: Path) -> None:
    malformed = _trace(
        tmp_path, tool_records=[{"tool_name": "x", "outcome": "malformed"}]
    )
    looped = _trace(tmp_path, done_reason="step_limit")

    assert classify_failure(malformed, ["file_exists"]) == "malformed_call"
    assert classify_failure(looped, ["file_exists"]) == "lost_context"
    assert classify_failure(_trace(tmp_path), ["tool_called"]) == "wrong_tool"
    assert classify_failure(_trace(tmp_path), []) == ""


def test_summary_applies_the_refusal_gate() -> None:
    from orchestrator.evaluation import RunResult

    def result(category: str, is_passed: bool) -> RunResult:
        return RunResult(
            "t", "adversarial", category, 1, is_passed, [], "", 1, 1, 1, 1, [], "m:1"
        )

    summary = summarise_results(
        [result("out_of_scope_path", True), result("out_of_scope_path", False)]
    )

    assert summary["gates"]["refusal"] == {
        "pass_rate": 0.5,
        "threshold": 1.0,
        "is_met": False,
    }


async def test_mcp_server_that_cannot_start_is_skipped(
    application: Application,
) -> None:
    from orchestrator.mcp_client import start_mcp_servers
    from orchestrator.settings import McpServerSettings

    broken = McpServerSettings("broken", ("definitely-not-a-real-exe-xyz",), 1, 1, {})

    connections = await asyncio.wait_for(
        start_mcp_servers((broken,), application.registry), timeout=10
    )

    assert connections == []
