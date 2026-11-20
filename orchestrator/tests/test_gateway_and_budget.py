"""Stream filtering, text tool-call recovery, locality and context budget."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.context_budget import (
    compact_conversation,
    conversation_tokens,
    estimate_tokens,
    truncate_tool_result,
)
from orchestrator.errors import NonLocalEndpointError
from orchestrator.gateway import ReasoningFilter, extract_text_tool_calls
from orchestrator.model_runtime import assert_endpoint_is_local

LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["Hello ", "world"], "Hello world"),
        (["<think>plan</think>Answer"], "Answer"),
        (["<thi", "nk>hidden</th", "ink>Shown"], "Shown"),
        (["Before <think>x</think> after"], "Before  after"),
        (["a < b and b > a"], "a < b and b > a"),
        (["<think>never closed"], ""),
    ],
)
def test_reasoning_filter_hides_think_spans_across_chunk_boundaries(
    chunks: list[str], expected: str
) -> None:
    reasoning_filter = ReasoningFilter()

    visible = "".join(reasoning_filter.feed(chunk) for chunk in chunks)

    assert visible == expected


def test_text_tool_call_is_recovered_and_removed_from_text() -> None:
    text = (
        "I will read it.\n"
        '<tool_call>{"name": "read_file", "arguments": {"path": "a.md"}}</tool_call>'
    )

    remaining_text, calls = extract_text_tool_calls(text)

    assert remaining_text == "I will read it."
    assert calls[0].name == "read_file"
    assert calls[0].arguments_json == '{"path": "a.md"}'


def test_malformed_text_tool_call_is_left_in_place() -> None:
    text = "<tool_call>{not json}</tool_call>"

    remaining_text, calls = extract_text_tool_calls(text)

    assert calls == []
    assert remaining_text == text


@pytest.mark.parametrize(
    "endpoint", ["http://127.0.0.1:58777", "http://localhost:5273"]
)
def test_loopback_endpoints_are_accepted(endpoint: str) -> None:
    assert_endpoint_is_local(endpoint, LOOPBACK_HOSTS)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.example.com/v1",
        "http://192.168.1.20:58777",
        "http://127.0.0.1.example.com",
        "",
    ],
)
def test_non_loopback_endpoints_are_refused(endpoint: str) -> None:
    with pytest.raises(NonLocalEndpointError):
        assert_endpoint_is_local(endpoint, LOOPBACK_HOSTS)


def test_short_tool_result_is_returned_unchanged() -> None:
    assert truncate_tool_result("short", max_tokens=1000) == "short"


def test_long_tool_result_keeps_head_tail_and_file_reference() -> None:
    result_text = "HEAD" + "x" * 20_000 + "TAIL"

    truncated = truncate_tool_result(
        result_text, max_tokens=1000, file_reference="big.txt"
    )

    assert truncated.startswith("HEAD")
    assert truncated.endswith("TAIL")
    assert "big.txt" in truncated
    assert estimate_tokens(truncated) < 1100


async def test_conversation_within_budget_is_not_compacted() -> None:
    messages: list[dict[str, object]] = [{"role": "user", "content": "hello"}]

    async def fail_if_called(transcript: str) -> str:
        raise AssertionError("summarise must not be called")

    assert await compact_conversation(messages, 1000, fail_if_called) == messages


async def test_compaction_summarises_old_turns_and_keeps_tool_pairs_together() -> None:
    messages: list[dict[str, Any]] = []
    for turn in range(6):
        messages.append({"role": "user", "content": f"question {turn} " + "pad " * 200})
        messages.append(
            {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{turn}"}]}
        )
        messages.append(
            {"role": "tool", "tool_call_id": f"c{turn}", "content": "result"}
        )

    async def summarise(transcript: str) -> str:
        return "short summary"

    compacted = await compact_conversation(messages, 400, summarise)

    assert "short summary" in str(compacted[0]["content"])
    assert compacted[1]["role"] != "tool"
    assert conversation_tokens(compacted) < conversation_tokens(messages)
    assert compacted[-1] == messages[-1]
