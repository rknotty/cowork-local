"""SQLite persistence for sessions, messages, tool calls and artefacts.

Every row that came from a model carries the model ID and version, so a
result can always be traced to the exact model that produced it (plan
section 7, step 8).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.errors import SessionNotFoundError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES session(session_id),
    role TEXT NOT NULL,
    message_json TEXT NOT NULL,
    model_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_call (
    tool_call_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES session(session_id),
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    tier INTEGER,
    approval_decision TEXT NOT NULL,
    outcome TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    model_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artefact (
    artefact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES session(session_id),
    relative_path TEXT NOT NULL,
    artefact_kind TEXT NOT NULL,
    model_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS message_session_idx ON message(session_id, message_id);
"""


DEFAULT_SESSION_TITLE = "New session"
MAX_TITLE_CHARACTERS = 120


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class SessionSummary:
    """A session as shown in the interface's session list."""

    session_id: str
    title: str
    workspace_path: str
    created_at: str


class SessionStore:
    """Thread-safe wrapper around one SQLite file."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        # The API event loop and worker threads share this connection; the
        # lock serialises access, which SQLite needs in that arrangement.
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.commit()

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._connection.close()

    def create_session(
        self,
        title: str,
        workspaces_root: Path,
        existing_workspace: Path | None = None,
    ) -> SessionSummary:
        """Create a session and its workspace folder.

        Args:
            title: Shown in the session list.
            workspaces_root: Where new workspaces are created.
            existing_workspace: Use this folder as the workspace instead of
                creating one. The terminal client uses it to work in place.
        """
        session_id = uuid.uuid4().hex
        workspace_path = existing_workspace or workspaces_root / session_id
        workspace_path.mkdir(parents=True, exist_ok=True)
        summary = SessionSummary(session_id, title, str(workspace_path), _now())
        with self._lock:
            self._connection.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?)",
                (session_id, title, summary.workspace_path, summary.created_at),
            )
            self._connection.commit()
        return summary

    def get_session(self, session_id: str) -> SessionSummary:
        """Fetch one session.

        Raises:
            SessionNotFoundError: If no such session exists.
        """
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM session WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise SessionNotFoundError("session not found", session_id=session_id)
        return SessionSummary(**dict(row))

    def list_sessions(self) -> list[SessionSummary]:
        """All sessions, newest first."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM session ORDER BY created_at DESC"
            ).fetchall()
        return [SessionSummary(**dict(row)) for row in rows]

    def rename_session(self, session_id: str, title: str) -> None:
        """Set a session's title."""
        with self._lock:
            self._connection.execute(
                "UPDATE session SET title = ? WHERE session_id = ?",
                (title, session_id),
            )
            self._connection.commit()

    def append_message(
        self, session_id: str, message: dict[str, object], model_id: str = ""
    ) -> None:
        """Persist one chat message in OpenAI wire format."""
        with self._lock:
            self._connection.execute(
                "INSERT INTO message (session_id, role, message_json, model_id, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    str(message.get("role", "")),
                    json.dumps(message, default=str),
                    model_id,
                    _now(),
                ),
            )
            self._connection.commit()

    def annotate_last_assistant_message(
        self, session_id: str, fields: dict[str, object]
    ) -> None:
        """Merge fields into the session's most recent assistant message.

        Used for facts only known once the turn has finished, such as its
        total duration. Does nothing if the session has no assistant message.
        """
        with self._lock:
            row = self._connection.execute(
                "SELECT message_id, message_json FROM message WHERE session_id = ? "
                "AND role = 'assistant' ORDER BY message_id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                return
            message = json.loads(row["message_json"])
            message.update(fields)
            self._connection.execute(
                "UPDATE message SET message_json = ? WHERE message_id = ?",
                (json.dumps(message, default=str), row["message_id"]),
            )
            self._connection.commit()

    def load_messages(self, session_id: str) -> list[dict[str, object]]:
        """The session's messages in order, each tagged with its model ID."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT message_json, model_id FROM message "
                "WHERE session_id = ? ORDER BY message_id",
                (session_id,),
            ).fetchall()
        messages = []
        for row in rows:
            message = json.loads(row["message_json"])
            message["model_id"] = row["model_id"]
            messages.append(message)
        return messages

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, object],
        tier: int | None,
        approval_decision: str,
        outcome: str,
        duration_ms: int,
        model_id: str,
    ) -> None:
        """Persist one tool call and how it was decided."""
        with self._lock:
            self._connection.execute(
                "INSERT INTO tool_call VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    session_id,
                    tool_name,
                    json.dumps(arguments, default=str),
                    tier,
                    approval_decision,
                    outcome,
                    duration_ms,
                    model_id,
                    _now(),
                ),
            )
            self._connection.commit()

    def record_artefact(
        self, session_id: str, relative_path: str, artefact_kind: str, model_id: str
    ) -> None:
        """Persist a file the agent produced in the workspace."""
        with self._lock:
            self._connection.execute(
                "INSERT INTO artefact (session_id, relative_path, artefact_kind, "
                "model_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, relative_path, artefact_kind, model_id, _now()),
            )
            self._connection.commit()

    def list_artefacts(self, session_id: str) -> list[dict[str, str]]:
        """Artefacts for a session, most recent last, one row per path."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT relative_path, artefact_kind, model_id, MAX(created_at) "
                "AS created_at FROM artefact WHERE session_id = ? "
                "GROUP BY relative_path ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]
