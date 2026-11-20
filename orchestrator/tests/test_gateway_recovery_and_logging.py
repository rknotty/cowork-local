"""The gateway serialises GPU calls and recovers from a stopped model service;
logging keeps a file and drops routine polling."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError

from orchestrator.errors import GatewayUnavailableError
from orchestrator.gateway import (
    EMBEDDING_BATCH_MAX_CHARACTERS,
    ModelGateway,
    plan_embedding_batches,
)
from orchestrator.logging_setup import RoutinePollingFilter, configure_logging
from orchestrator.settings import load_settings
from orchestrator.tests.conftest import FakeRuntime


def _connection_error() -> APIConnectionError:
    # This openai release is built on httpx2, so its errors need its Request type.
    return APIConnectionError(
        request=httpx2.Request("POST", "http://127.0.0.1:1/v1/embeddings")
    )


def _embedding_response(count: int) -> Any:
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=[1.0, 0.0]) for _ in range(count)],
        usage=SimpleNamespace(prompt_tokens=count),
    )


class OverlapProbe:
    """Fake chat and embedding endpoints that record concurrent calls."""

    def __init__(self) -> None:
        self.active_calls = 0
        self.peak_active_calls = 0

    async def _occupy(self) -> None:
        self.active_calls += 1
        self.peak_active_calls = max(self.peak_active_calls, self.active_calls)
        await asyncio.sleep(0.01)
        self.active_calls -= 1

    async def create_embeddings(self, **request: Any) -> Any:
        await self._occupy()
        return _embedding_response(len(request["input"]))

    async def create_chat(self, **request: Any) -> Any:
        await self._occupy()

        async def stream() -> Any:
            yield SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(content="ok", tool_calls=None),
                    )
                ],
            )

        return stream()


async def test_chat_and_embedding_never_reach_the_gpu_at_the_same_time() -> None:
    probe = OverlapProbe()
    gateway = ModelGateway(load_settings(), FakeRuntime())
    gateway._client = SimpleNamespace(  # type: ignore[assignment]
        embeddings=SimpleNamespace(create=probe.create_embeddings),
        chat=SimpleNamespace(completions=SimpleNamespace(create=probe.create_chat)),
    )

    await asyncio.gather(
        gateway.embed(["passage"] * 100),
        gateway.chat("orchestrator", [{"role": "user", "content": "hi"}]),
        gateway.embed(["query"]),
    )

    assert probe.peak_active_calls == 1


class RestartingRuntime(FakeRuntime):
    """A runtime whose daemon is down until started."""

    def __init__(self) -> None:
        self.is_running = False
        self.start_count = 0
        self.loaded: list[str] = []

    def resolve_endpoint(self) -> str:
        if not self.is_running:
            raise GatewayUnavailableError("foundry daemon is not running")
        return "http://127.0.0.1:2"

    def start_service(self) -> None:
        self.start_count += 1
        self.is_running = True

    def load_model(self, alias: str) -> None:
        self.loaded.append(alias)


async def test_embedding_restarts_a_stopped_service_and_reloads_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RestartingRuntime()
    runtime.is_running = True
    gateway = ModelGateway(load_settings(), runtime)
    calls: list[str] = []

    async def crash_then_answer(**request: Any) -> Any:
        calls.append("call")
        if len(calls) == 1:
            runtime.is_running = False  # the daemon dies mid-request
            raise _connection_error()
        return _embedding_response(len(request["input"]))

    def fake_client(**_: Any) -> Any:
        return SimpleNamespace(embeddings=SimpleNamespace(create=crash_then_answer))

    monkeypatch.setattr("orchestrator.gateway.AsyncOpenAI", fake_client)

    result = await gateway.embed(["passage"])

    assert len(result.vectors) == 1
    assert runtime.start_count == 1
    assert runtime.loaded == ["qwen3-embedding-0.6b", "qwen3-embedding-0.6b"]


async def test_service_is_not_restarted_again_within_the_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = RestartingRuntime()
    gateway = ModelGateway(load_settings(), runtime)

    async def always_crash(**_: Any) -> Any:
        runtime.is_running = False
        raise _connection_error()

    monkeypatch.setattr(
        "orchestrator.gateway.AsyncOpenAI",
        lambda **_: SimpleNamespace(embeddings=SimpleNamespace(create=always_crash)),
    )

    with pytest.raises(GatewayUnavailableError):
        await gateway.embed(["passage"])

    assert runtime.start_count == 1


def test_embedding_batches_are_capped_by_size_as_well_as_count() -> None:
    spreadsheet_passages = ["|1|2|" * 440] * 32  # 2,200 characters each
    short_passages = ["leave policy"] * 70

    dense_batches = plan_embedding_batches(spreadsheet_passages)
    short_batches = plan_embedding_batches(short_passages)
    oversized = plan_embedding_batches(["x" * 20_000, "y"])

    assert [len(batch) for batch in dense_batches] == [7, 7, 7, 7, 4]
    assert all(
        sum(map(len, batch)) <= EMBEDDING_BATCH_MAX_CHARACTERS
        for batch in dense_batches
    )
    assert [len(batch) for batch in short_batches] == [32, 32, 6]
    # Truncated to the per-input limit, which then leaves room for the next.
    assert [list(map(len, batch)) for batch in oversized] == [[8192, 1]]


def _access_record(method: str, status_code: int) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", method, "/api/health", "1.1", status_code),
        None,
    )


def test_polling_filter_drops_successful_gets_only() -> None:
    polling_filter = RoutinePollingFilter()

    assert not polling_filter.filter(_access_record("GET", 200))
    assert polling_filter.filter(_access_record("GET", 500))
    assert polling_filter.filter(_access_record("POST", 202))
    assert polling_filter.filter(
        logging.LogRecord("orchestrator", logging.INFO, "", 0, "x", None, None)
    )


def test_configure_logging_writes_json_lines_to_a_file(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    previous_handlers, previous_level = root_logger.handlers[:], root_logger.level
    try:
        log_file = configure_logging(tmp_path / "logs")
        logging.getLogger("orchestrator.test").info(
            "Indexing progress", extra={"processed_file_count": 25}
        )
        for handler in root_logger.handlers:
            handler.flush()
    finally:
        for handler in root_logger.handlers:
            handler.close()
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)

    assert log_file == tmp_path / "logs" / "orchestrator.log"
    record = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
    assert record["message"] == "Indexing progress"
    assert record["processed_file_count"] == 25
