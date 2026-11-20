"""Shared fixtures: an application wired to a scripted model."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from orchestrator.bootstrap import Application, build_application
from orchestrator.events import AgentEvent
from orchestrator.gateway import ChatResult, EmbeddingResult, ToolCallRequest
from orchestrator.knowledge.index import KnowledgeIndex
from orchestrator.model_runtime import ResolvedModel
from orchestrator.settings import load_settings
from orchestrator.toolkit.context import ToolContext

FAKE_MODEL_ID = "fake-model:1"
EMBEDDING_DIMENSIONS = 16


class FakeRuntime:
    """Stands in for Foundry Local management."""

    def resolve_endpoint(self) -> str:
        return "http://127.0.0.1:1"

    def resolve_model(self, alias: str) -> ResolvedModel:
        return ResolvedModel(alias, FAKE_MODEL_ID, "test", "none", True)

    def start_service(self) -> None:
        return None

    def load_model(self, alias: str) -> None:
        return None

    def unload_model(self, alias: str) -> None:
        return None

    def transcribe_file(self, alias: str, audio_path: Path) -> tuple[str, str]:
        return "scripted transcript", FAKE_MODEL_ID


def tool_call_reply(name: str, arguments: dict[str, object] | str) -> ChatResult:
    """A scripted model reply that calls one tool."""
    arguments_json = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ChatResult(
        text="",
        tool_calls=[ToolCallRequest(f"call_{name}", name, arguments_json)],
        model_id=FAKE_MODEL_ID,
        prompt_tokens=10,
        completion_tokens=5,
        duration_ms=1,
        finish_reason="tool_calls",
    )


def text_reply(text: str) -> ChatResult:
    """A scripted model reply with a plain answer."""
    return ChatResult(text, [], FAKE_MODEL_ID, 10, 5, 1, "stop")


class ScriptedGateway:
    """Returns queued chat replies and deterministic embeddings."""

    def __init__(self) -> None:
        self.replies: list[ChatResult] = []
        self.chat_requests: list[dict[str, Any]] = []

    async def chat(
        self,
        role: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> ChatResult:
        self.chat_requests.append({"role": role, "messages": messages, "tools": tools})
        reply = self.replies.pop(0) if self.replies else text_reply("No more replies.")
        if on_text_delta and reply.text:
            on_text_delta(reply.text)
        return reply

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        vectors = []
        for text in texts:
            vector = [0.0] * EMBEDDING_DIMENSIONS
            for word in text.lower().split():
                vector[hash(word) % EMBEDDING_DIMENSIONS] += 1.0
            vectors.append(vector)
        return EmbeddingResult(vectors, FAKE_MODEL_ID, 0, 1)

    async def health(self) -> dict[str, object]:
        return {"is_healthy": True, "roles": {"orchestrator": FAKE_MODEL_ID}}


@pytest.fixture
def application(tmp_path: Path) -> Iterator[Application]:
    """An application with real tools and stores, and a scripted model."""
    settings = load_settings(data_directory=tmp_path / "data")
    built_application = build_application(settings, FakeRuntime())
    scripted = ScriptedGateway()
    built_application.services.gateway = scripted  # type: ignore[assignment]

    async def embed_with_script(texts: list[str]) -> list[list[float]]:
        return (await scripted.embed(texts)).vectors

    # The index built by build_application captured the real gateway; rebuild
    # it so no test can reach a model endpoint.
    built_application.services.knowledge.close()
    built_application.services.knowledge = KnowledgeIndex(
        tmp_path / "data" / "knowledge-test.sqlite", embed_with_script
    )
    yield built_application
    built_application.services.store.close()
    built_application.services.knowledge.close()


@pytest.fixture
def scripted_gateway(application: Application) -> ScriptedGateway:
    """The scripted model behind the application fixture."""
    return application.services.gateway  # type: ignore[return-value]


@pytest.fixture
def emitted_events() -> list[AgentEvent]:
    """Collects every event a test's tool context emits."""
    return []


@pytest.fixture
def tool_context(
    application: Application, emitted_events: list[AgentEvent]
) -> ToolContext:
    """A tool context on a fresh session and workspace."""
    session = application.services.store.create_session(
        "test", application.services.settings.data_directory / "workspaces"
    )
    return application.create_tool_context(session.session_id, emitted_events.append)
