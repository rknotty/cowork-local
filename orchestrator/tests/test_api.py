"""HTTP API: error shape, file confinement and the session flow."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestrator.api import create_app
from orchestrator.bootstrap import Application
from orchestrator.tests.conftest import ScriptedGateway, text_reply


@pytest.fixture
def client(application: Application) -> TestClient:
    return TestClient(create_app(application))


def _create_session(client: TestClient) -> str:
    response = client.post("/api/sessions", json={"title": "Test"})
    assert response.status_code == 201
    return str(response.json()["session_id"])


def test_health_reports_offline_and_bound_models(client: TestClient) -> None:
    body = client.get("/api/health").json()

    assert body["is_healthy"] is True
    assert body["is_offline"] is True
    assert body["sandbox_state"] in ("ready", "unavailable")
    assert "orchestrator" in body["roles"]


def test_unknown_session_returns_the_standard_error_shape(client: TestClient) -> None:
    response = client.get("/api/sessions/does-not-exist/messages")

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "SESSION_NOT_FOUND"
    assert set(body) == {"error", "message", "trace_id"}
    assert body["trace_id"] == response.headers["X-Trace-Id"]


def test_invalid_approval_decision_is_rejected_at_the_boundary(
    client: TestClient,
) -> None:
    session_id = _create_session(client)

    response = client.post(
        f"/api/sessions/{session_id}/approvals/abc", json={"decision": "maybe"}
    )

    assert response.status_code == 422


def test_uploaded_file_round_trips_and_is_served_sandboxed(client: TestClient) -> None:
    session_id = _create_session(client)

    upload = client.put(
        f"/api/sessions/{session_id}/files/notes/a.html", content=b"<p>hi</p>"
    )
    download = client.get(f"/api/sessions/{session_id}/files/notes/a.html")
    listing = client.get(f"/api/sessions/{session_id}/files").json()

    assert upload.status_code == 204
    assert download.content == b"<p>hi</p>"
    assert "sandbox" in download.headers["Content-Security-Policy"]
    assert listing[0]["relative_path"] == "notes/a.html"
    assert listing[0]["is_changed_this_session"] is False


@pytest.mark.parametrize(
    "escaping_path", ["..%2F..%2Fsessions.sqlite", "%2E%2E/%2E%2E/audit/audit.jsonl"]
)
def test_file_routes_cannot_leave_the_workspace(
    client: TestClient, escaping_path: str
) -> None:
    session_id = _create_session(client)

    response = client.get(f"/api/sessions/{session_id}/files/{escaping_path}")

    assert response.status_code in (403, 404)
    assert response.status_code != 200


def test_folders_must_be_existing_absolute_paths(client: TestClient) -> None:
    response = client.put("/api/folders", json={"folders": ["relative/path"]})

    assert response.status_code == 400
    assert response.json()["error"] == "TOOL_EXECUTION_FAILED"


def test_memory_api_refuses_sensitive_content_without_echoing_it(
    client: TestClient,
) -> None:
    secret_text = "password: example-not-real"

    response = client.put(
        "/api/memory/preferences", json={"description": "prefs", "content": secret_text}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "SENSITIVE_CONTENT_REFUSED"
    assert "example-not-real" not in response.text


def test_message_turn_persists_user_and_assistant_messages(
    client: TestClient, scripted_gateway: ScriptedGateway
) -> None:
    scripted_gateway.replies = [text_reply("Hello there.")]
    session_id = _create_session(client)

    with client:
        accepted = client.post(
            f"/api/sessions/{session_id}/messages", json={"text": "Hi"}
        )
        messages = []
        for _ in range(50):
            messages = client.get(f"/api/sessions/{session_id}/messages").json()
            if len(messages) == 2:
                break

    assert accepted.status_code == 202
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["model_id"] == "fake-model:1"
