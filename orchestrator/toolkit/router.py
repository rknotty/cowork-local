"""The tool router (plan section 9).

Every tool call passes through `ToolRouter.execute`: validate, check the
tier, ask for approval where policy requires it, execute, audit, return. No
tool is callable any other way.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import jsonschema

from orchestrator.audit import AuditRecord, hash_content
from orchestrator.context_budget import truncate_tool_result
from orchestrator.errors import (
    OrchestratorError,
    PathNotAllowedError,
    ToolArgumentsInvalidError,
    ToolDeniedError,
    ToolNotFoundError,
)
from orchestrator.events import AgentEvent, EventType
from orchestrator.toolkit.context import ToolContext
from orchestrator.toolkit.registry import ToolDefinition, ToolRegistry, ToolTier

logger = logging.getLogger(__name__)

APPROVAL_NOT_REQUIRED = "not_required"
APPROVAL_SESSION = "allow_session"
APPROVAL_ONCE = "allow_once"
APPROVAL_DENIED = "deny"
RESULT_PREVIEW_CHARACTERS = 600


@dataclass(frozen=True)
class ToolOutcome:
    """Result of routing one tool call, ready to append to the conversation."""

    text: str
    outcome: str
    # True when the model's call itself was malformed (unknown tool or bad
    # arguments). The agent loop counts these against the repair allowance.
    is_malformed_call: bool = False


def parse_arguments(definition: ToolDefinition, arguments_json: str) -> dict[str, Any]:
    """Parse and validate arguments against the tool's schema.

    Raises:
        ToolArgumentsInvalidError: Naming the fault, so the model can fix it.
    """
    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        raise ToolArgumentsInvalidError(
            f"arguments are not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(arguments, dict):
        raise ToolArgumentsInvalidError("arguments must be a JSON object")
    validator = jsonschema.Draft202012Validator(definition.parameters)
    first_error = next(iter(validator.iter_errors(arguments)), None)
    if first_error is not None:
        location = "/".join(str(part) for part in first_error.absolute_path) or "root"
        raise ToolArgumentsInvalidError(f"{first_error.message} (at {location})")
    return arguments


def describe_repair(
    definition_or_none: ToolDefinition | None, error: OrchestratorError
) -> str:
    """Build the short error returned to the model after a malformed call."""
    if isinstance(error, ToolNotFoundError):
        valid_names = error.context.get("valid_tool_names", [])
        return (
            f"Error: there is no tool named '{error.context.get('tool_name')}'. "
            f"Valid tools: {', '.join(str(name) for name in valid_names)}. "
            "Call find_tool to look for others."
        )
    schema_text = (
        json.dumps(definition_or_none.parameters) if definition_or_none else "{}"
    )
    return f"Error: {error.detail}. Expected arguments schema: {schema_text}"


class ToolRouter:
    """Applies tier policy to every tool call and records what happened."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry:
        """The registry this router dispatches to."""
        return self._registry

    async def execute(
        self, context: ToolContext, call_id: str, tool_name: str, arguments_json: str
    ) -> ToolOutcome:
        """Route one tool call. Never raises for a failure the model caused.

        Refusals, denials and tool failures come back as text the model can
        read and act on. Each path writes exactly one audit record.
        """
        started_at = time.monotonic()
        definition: ToolDefinition | None = None
        arguments: dict[str, Any] = {}
        approval_decision = APPROVAL_NOT_REQUIRED
        try:
            definition = self._registry.get(tool_name)
            arguments = parse_arguments(definition, arguments_json)
        except (ToolNotFoundError, ToolArgumentsInvalidError) as error:
            repair_text = describe_repair(definition, error)
            self._record(
                context,
                tool_name,
                arguments,
                definition,
                approval_decision,
                "malformed",
                error.error_code,
                repair_text,
                started_at,
            )
            return ToolOutcome(repair_text, "error", is_malformed_call=True)

        context.emit(
            AgentEvent(
                EventType.TOOL_CALL,
                {
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "tier": int(definition.tier),
                    "summary": _summarise_arguments(definition, arguments),
                },
            )
        )
        try:
            approval_decision = await self._decide_approval(
                context, call_id, definition, arguments
            )
            output = await definition.handler(context, arguments)
            result_text = truncate_tool_result(
                output.text,
                context.services.settings.tool_result_max_tokens,
                output.file_reference,
            )
            outcome, error_code = "ok", ""
        except ToolDeniedError as error:
            approval_decision = APPROVAL_DENIED
            result_text = (
                "Denied: the user did not approve this action. Do not retry it."
            )
            outcome, error_code = "denied", error.error_code
        except OrchestratorError as error:
            # Expected failures (path refused, file missing, sandbox down):
            # the model gets the safe message and can change course.
            result_text = f"Error: {error.safe_message} ({error.detail})"
            outcome, error_code = "error", error.error_code
            if isinstance(error, PathNotAllowedError):
                logger.warning(
                    "Tool call refused: path outside allowed folders",
                    extra={"tool_name": tool_name, "error_code": error.error_code},
                )
        self._record(
            context,
            tool_name,
            arguments,
            definition,
            approval_decision,
            outcome,
            error_code,
            result_text,
            started_at,
        )
        context.emit(
            AgentEvent(
                EventType.TOOL_RESULT,
                {
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "outcome": outcome,
                    "result_preview": result_text[:RESULT_PREVIEW_CHARACTERS],
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                },
            )
        )
        return ToolOutcome(result_text, outcome)

    async def _decide_approval(
        self,
        context: ToolContext,
        call_id: str,
        definition: ToolDefinition,
        arguments: dict[str, Any],
    ) -> str:
        """Apply the tier policy. Raises ToolDeniedError when the user refuses."""
        target = str(arguments.get(definition.target_argument, ""))
        if not self._requires_approval(context, definition, target):
            return APPROVAL_NOT_REQUIRED
        is_session_approval_allowed = definition.tier != ToolTier.EXTERNAL
        if (
            is_session_approval_allowed
            and definition.name in context.session_approved_tools
        ):
            return APPROVAL_SESSION
        request_id, future = context.broker.open_request()
        context.emit(
            AgentEvent(
                EventType.APPROVAL_REQUEST,
                {
                    "request_id": request_id,
                    "call_id": call_id,
                    "tool_name": definition.name,
                    "tier": int(definition.tier),
                    "action": _summarise_arguments(definition, arguments),
                    "target": target,
                },
            )
        )
        # Cancellation (the stop button) propagates from here on purpose.
        decision = await future
        if decision == APPROVAL_SESSION and is_session_approval_allowed:
            context.session_approved_tools.add(definition.name)
            return APPROVAL_SESSION
        if decision in (APPROVAL_ONCE, APPROVAL_SESSION):
            return APPROVAL_ONCE
        raise ToolDeniedError("user denied the action", tool_name=definition.name)

    def _requires_approval(
        self, context: ToolContext, definition: ToolDefinition, target: str
    ) -> bool:
        if definition.tier == ToolTier.EXTERNAL:
            return True
        if definition.tier == ToolTier.WRITE and target:
            # Raises PathNotAllowedError for a path outside every allowed
            # root, which refuses the call before the user is ever asked.
            canonical_path = context.allowlist.resolve_allowed(target)
            return not context.allowlist.is_inside_workspace(canonical_path)
        return False

    def _record(
        self,
        context: ToolContext,
        tool_name: str,
        arguments: dict[str, Any],
        definition: ToolDefinition | None,
        approval_decision: str,
        outcome: str,
        error_code: str,
        result_text: str,
        started_at: float,
    ) -> None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        tier = int(definition.tier) if definition else None
        audited_arguments = _redact_large_arguments(arguments)
        context.services.audit_log.append(
            AuditRecord(
                kind="tool_call",
                session_id=context.session_id,
                model_id=context.model_id,
                tool_name=tool_name,
                tool_arguments=audited_arguments,
                tier=tier,
                approval_decision=approval_decision,
                outcome=outcome,
                error_code=error_code,
                input_hash=hash_content(arguments),
                result_hash=hash_content(result_text),
                duration_ms=duration_ms,
            )
        )
        context.services.store.record_tool_call(
            context.session_id,
            tool_name,
            audited_arguments,
            tier,
            approval_decision,
            outcome,
            duration_ms,
            context.model_id,
        )


def _summarise_arguments(definition: ToolDefinition, arguments: dict[str, Any]) -> str:
    """One line describing the call for a tool card or approval prompt."""
    target = arguments.get(definition.target_argument)
    if target:
        return f"{definition.name}: {target}"
    compact = json.dumps(arguments, default=str)
    return f"{definition.name} {compact[:120]}"


def _redact_large_arguments(arguments: dict[str, Any]) -> dict[str, object]:
    """Keep identifiers in the audit log, replace bulky content with its hash.

    The log is evidence of what was done, not a second copy of documents.
    """
    audited: dict[str, object] = {}
    for name, argument in arguments.items():
        if isinstance(argument, str) and len(argument) > 200:
            audited[name] = f"[sha256:{hash_content(argument)} length:{len(argument)}]"
        elif isinstance(argument, dict | list):
            audited[name] = f"[sha256:{hash_content(argument)}]"
        else:
            audited[name] = argument
    return audited
