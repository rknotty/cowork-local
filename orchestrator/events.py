"""The event stream contract between orchestrator and interface.

This is fixed first because the interface depends on it (plan section 7,
step 1). The same contract is documented for interface authors in
`docs/event-contract.md`; change both together.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    """Every event the orchestrator can emit on a session stream."""

    TEXT_DELTA = "text_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUEST = "approval_request"
    QUESTION = "question"
    TASK_UPDATE = "task_update"
    ARTEFACT = "artefact"
    USAGE = "usage"
    KNOWLEDGE_ACCESS = "knowledge_access"
    ERROR = "error"
    DONE = "done"


@dataclass(frozen=True)
class AgentEvent:
    """One event on a session stream."""

    type: EventType
    # JSON-shaped and validated by the producer; Any keeps consumers free of
    # casts while the wire format stays documented in docs/event-contract.md.
    payload: dict[str, Any] = field(default_factory=dict)

    def to_server_sent_event(self) -> str:
        """Encode as a server-sent events frame."""
        return f"event: {self.type.value}\ndata: {json.dumps(self.payload, default=str)}\n\n"
