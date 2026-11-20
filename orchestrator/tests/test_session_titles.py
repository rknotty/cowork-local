"""Renaming sessions, and automatic titles for new ones."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestrator.agent_loop import clean_title
from orchestrator.api import create_app
from orchestrator.bootstrap import Application
from orchestrator.errors import GatewayUnavailableError
from orchestrator.store import DEFAULT_SESSION_TITLE
from orchestrator.tests.conftest import ScriptedGateway, text_reply
from orchestrator.toolkit.context import ToolContext


@pytest.mark.parametrize(
    ("model_text", "expected"),
    [
        ("Quarterly budget review", "Quarterly budget review"),
        ('"Quarterly budget review."', "Quarterly budget review"),
        ("Title: Partner keynote actions\nExtra line", "Partner keynote actions"),
        ("\n\n**Leave policy question**", "Leave policy question"),
        ("x" * 200, "x" * 60),
        ("   ", ""),
    ],
)
def test_model_titles_are_cleaned_to_one_tidy_line(
    model_text: str, expected: str
) -> None:
    assert clean_title(model_text) == expected


@pytest.fixture
def default_titled_context(
    application: Application, tool_context: ToolContext
) -> ToolContext:
    application.services.store.rename_session(
        tool_context.session_id, DEFAULT_SESSION_TITLE
    )
    return tool_context


async def test_new_session_is_titled_after_its_first_answer(
    application: Application,
    scripted_gateway: ScriptedGateway,
    default_titled_context: ToolContext,
) -> None:
    scripted_gateway.replies = [
        text_reply("Here is the summary."),
        text_reply("Partner keynote summary"),
    ]

    await application.agent_loop.run_turn(
        default_titled_context, "Summarise the keynote"
    )

    session = application.services.store.get_session(default_titled_context.session_id)
    assert session.title == "Partner keynote summary"
    assert scripted_gateway.chat_requests[1]["role"] == "utility"


async def test_a_name_the_user_chose_is_never_replaced(
    application: Application,
    scripted_gateway: ScriptedGateway,
    default_titled_context: ToolContext,
) -> None:
    application.services.store.rename_session(
        default_titled_context.session_id, "My name"
    )
    scripted_gateway.replies = [text_reply("Answer.")]

    await application.agent_loop.run_turn(default_titled_context, "Question")

    assert (
        application.services.store.get_session(default_titled_context.session_id).title
        == "My name"
    )
    assert len(scripted_gateway.chat_requests) == 1


async def test_titling_failure_leaves_the_name_and_the_answer_intact(
    application: Application,
    scripted_gateway: ScriptedGateway,
    default_titled_context: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted_gateway.replies = [text_reply("Answer.")]
    original_chat = scripted_gateway.chat

    async def chat_failing_for_utility(
        role: str, *args: object, **kwargs: object
    ) -> object:
        if role == "utility":
            raise GatewayUnavailableError("down")
        return await original_chat(role, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(scripted_gateway, "chat", chat_failing_for_utility)

    reason = await application.agent_loop.run_turn(default_titled_context, "Question")

    assert reason == "answered"
    session = application.services.store.get_session(default_titled_context.session_id)
    assert session.title == DEFAULT_SESSION_TITLE


def test_rename_endpoint_tidies_and_saves_the_name(application: Application) -> None:
    with TestClient(create_app(application)) as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]

        renamed = client.patch(
            f"/api/sessions/{session_id}", json={"title": "  Budget   review  "}
        )
        listed = client.get("/api/sessions").json()

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Budget review"
    assert listed[0]["title"] == "Budget review"


@pytest.mark.parametrize(
    ("title", "status"), [("   ", 400), ("", 422), ("x" * 121, 422)]
)
def test_rename_rejects_blank_or_overlong_names(
    application: Application, title: str, status: int
) -> None:
    with TestClient(create_app(application)) as client:
        session_id = client.post("/api/sessions", json={}).json()["session_id"]

        response = client.patch(f"/api/sessions/{session_id}", json={"title": title})

    assert response.status_code == status


def test_rename_of_an_unknown_session_is_not_found(application: Application) -> None:
    with TestClient(create_app(application)) as client:
        response = client.patch("/api/sessions/nope", json={"title": "Name"})

    assert response.status_code == 404
