"""Per-session state handed to every tool handler."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orchestrator.events import AgentEvent, EventType
from orchestrator.paths import PathAllowlist

if TYPE_CHECKING:
    from orchestrator.services import Services

EventEmitter = Callable[[AgentEvent], None]

APPROVAL_DECISIONS = ("allow_once", "allow_session", "deny")


@dataclass
class PlannedTask:
    """One step on the model's task list."""

    id: int
    title: str
    status: str = "pending"


class InteractionBroker:
    """Parks the agent loop on a user decision and resumes it when one arrives.

    Used for approval prompts and for `ask_user` questions. The interface
    answers through the API, which calls `resolve`.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}

    def open_request(self) -> tuple[str, asyncio.Future[str]]:
        """Create a pending request and return its ID and future."""
        request_id = uuid.uuid4().hex
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        return request_id, future

    def resolve(self, request_id: str, answer: str) -> bool:
        """Deliver the user's answer. Returns False for an unknown request."""
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(answer)
        return True

    def cancel_all(self) -> None:
        """Release every parked request, used when the user presses stop."""
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()


@dataclass
class ToolContext:
    """Everything a tool may use. One per session."""

    session_id: str
    allowlist: PathAllowlist
    services: Services
    emit: EventEmitter
    broker: InteractionBroker = field(default_factory=InteractionBroker)
    tasks: list[PlannedTask] = field(default_factory=list)
    # Tools the user approved "for this session". Tier 3 is never added.
    session_approved_tools: set[str] = field(default_factory=set)
    # Deferred tools made callable this session, through find_tool or a
    # loaded skill's allowed-tools.
    discovered_tool_names: set[str] = field(default_factory=set)
    loaded_skill_names: set[str] = field(default_factory=set)
    changed_paths: set[str] = field(default_factory=set)
    model_id: str = ""

    def emit_task_update(self) -> None:
        """Send the full task list to the interface."""
        self.emit(
            AgentEvent(
                EventType.TASK_UPDATE,
                {
                    "tasks": [
                        {"id": task.id, "title": task.title, "status": task.status}
                        for task in self.tasks
                    ]
                },
            )
        )
