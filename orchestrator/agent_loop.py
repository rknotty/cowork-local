"""The agent loop (plan section 7, step 3).

Send messages and tools. If the reply has tool calls, route each one, append
the results and repeat. Stop on a plain answer, the step limit or
cancellation. One generation runs at a time: there is one GPU.

This is a hand-written loop rather than Microsoft Agent Framework. The reason
is recorded in docs/adr/0002-hand-written-agent-loop.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid

from orchestrator.audit import AuditRecord, hash_content
from orchestrator.context_budget import (
    ContextBudget,
    Message,
    compact_conversation,
    conversation_tokens,
    estimate_tokens,
)
from orchestrator.errors import OrchestratorError
from orchestrator.events import AgentEvent, EventType
from orchestrator.gateway import ChatResult, ToolCallRequest
from orchestrator.logging_setup import correlation_id_var, session_id_var
from orchestrator.prompt_builder import build_system_prompt, load_prompts
from orchestrator.services import Services
from orchestrator.store import DEFAULT_SESSION_TITLE
from orchestrator.toolkit.context import ToolContext
from orchestrator.toolkit.router import ToolRouter

logger = logging.getLogger(__name__)

ORCHESTRATOR_ROLE = "orchestrator"
UTILITY_ROLE = "utility"
DONE_ANSWERED = "answered"
DONE_STEP_LIMIT = "step_limit"
DONE_CANCELLED = "cancelled"
DONE_ERROR = "error"


# Recorded as the author of calls the orchestrator makes on the user's behalf,
# so the transcript never attributes them to the model.
HARNESS_MODEL_ID = "harness"
# The first message is enough to name a session; long pastes are cut so
# titling stays a sub-second call.
TITLE_SOURCE_CHARACTERS = 1500
MAX_GENERATED_TITLE_CHARACTERS = 60
CHAT_MESSAGE_FIELDS = frozenset({"role", "content", "tool_calls", "tool_call_id"})

REPEATED_CALL_MESSAGE = (
    "You already called {tool_name} with exactly these arguments in this turn. "
    "Its result is above. Do not repeat it: answer the user now, or call a "
    "different tool."
)


def clean_title(model_text: str) -> str:
    """Turn a model's suggested title into a tidy one-line session name.

    Small models wrap titles in quotes, prefix "Title:", or add a full stop;
    this strips those. Returns "" when nothing usable is left.
    """
    first_line = next((line for line in model_text.splitlines() if line.strip()), "")
    without_prefix = re.sub(
        r"^\s*(session\s+)?title\s*:\s*", "", first_line, flags=re.IGNORECASE
    )
    title = " ".join(without_prefix.split()).strip(" \"'`*.#")
    return title[:MAX_GENERATED_TITLE_CHARACTERS].rstrip()


def _normalise_arguments(arguments_json: str) -> str:
    """Canonical form of a call's arguments, so key order does not hide a repeat."""
    try:
        return json.dumps(json.loads(arguments_json or "{}"), sort_keys=True)
    except json.JSONDecodeError:
        return arguments_json


def wrap_untrusted(tool_name: str, result_text: str) -> str:
    """Delimit tool output so the model treats it as data, not instruction.

    This is a mitigation, not a control: a local model is more easily steered
    by injected text than a frontier one. The real control is tier 3
    approvals (plan section 13, control 6).
    """
    return f'<tool_output tool="{tool_name}">\n{result_text}\n</tool_output>'


class AgentLoop:
    """Runs one user turn to completion."""

    def __init__(self, services: Services, router: ToolRouter) -> None:
        self._services = services
        self._router = router
        self._prompts = load_prompts(services.settings.repository_root)
        role_settings = services.settings.roles[ORCHESTRATOR_ROLE]
        self._budget = ContextBudget.from_settings(
            role_settings.context_limit_tokens, services.settings.context_budget
        )
        self._context_limit_tokens = role_settings.context_limit_tokens
        # One GPU means one generation at a time. Turns from different
        # sessions queue here rather than competing for the model.
        self._generation_lock = asyncio.Lock()

    async def run_turn(self, context: ToolContext, user_text: str) -> str:
        """Run the loop for one user message and return the stop reason.

        Emits events through `context.emit` throughout. Always ends by
        emitting exactly one `done` event, including on failure and
        cancellation, so the interface never waits on a dead turn.
        """
        # Started before the generation lock, so the time includes any wait
        # behind another session's turn: it is what the user experienced.
        started_at = time.monotonic()
        answered_at: float | None = None
        correlation_id = uuid.uuid4().hex
        correlation_id_var.set(correlation_id)
        session_id_var.set(context.session_id)
        store = self._services.store
        user_message: Message = {"role": "user", "content": user_text}
        store.append_message(context.session_id, user_message)
        reason = DONE_ERROR
        try:
            async with self._generation_lock:
                await self._load_requested_skills(context, user_text)
                reason = await self._run_steps(context)
                answered_at = time.monotonic()
                if reason == DONE_ANSWERED:
                    await self._title_new_session(context, user_text)
        except asyncio.CancelledError:
            reason = DONE_CANCELLED
            context.broker.cancel_all()
            logger.info("Turn cancelled by the user")
        except OrchestratorError as error:
            logger.exception(
                "Turn failed", extra={"error_code": error.error_code, **error.context}
            )
            context.emit(
                AgentEvent(
                    EventType.ERROR,
                    {
                        "error": error.error_code,
                        "message": error.safe_message,
                        "trace_id": correlation_id,
                    },
                )
            )
        finally:
            # The clock stops at the answer: titling the session afterwards
            # is housekeeping, not part of the response the user waited for.
            duration_ms = int(((answered_at or time.monotonic()) - started_at) * 1000)
            logger.info(
                "Turn finished", extra={"reason": reason, "duration_ms": duration_ms}
            )
            if reason == DONE_ANSWERED:
                # Stored with the answer so the time survives a page reload.
                store.annotate_last_assistant_message(
                    context.session_id, {"turn_duration_ms": duration_ms}
                )
            context.emit(
                AgentEvent(
                    EventType.DONE,
                    {
                        "reason": reason,
                        "model_id": context.model_id,
                        "duration_ms": duration_ms,
                    },
                )
            )
        return reason

    async def _run_steps(self, context: ToolContext) -> str:
        consecutive_failed_calls = 0
        max_repairs = self._services.settings.max_repair_attempts
        calls_made_this_turn: set[tuple[str, str]] = set()
        for _ in range(self._services.settings.max_steps):
            messages = await self._assemble_messages(context)
            result = await self._call_model(context, messages)
            if not result.tool_calls:
                return self._finish_with_answer(context, result)
            self._persist_assistant(context, result)
            for tool_call in result.tool_calls:
                is_failed_call = await self._execute_tool_call(
                    context, tool_call, calls_made_this_turn
                )
                consecutive_failed_calls = (
                    consecutive_failed_calls + 1 if is_failed_call else 0
                )
            if consecutive_failed_calls > max_repairs:
                self._emit_error(
                    context,
                    "TOOL_CALLS_MALFORMED",
                    "The model kept producing invalid or repeated tool calls. "
                    "Try rephrasing the request or a simpler task.",
                )
                return DONE_ERROR
        return DONE_STEP_LIMIT

    async def _title_new_session(self, context: ToolContext, user_text: str) -> None:
        """Name a session from its first message, if it still has the default name.

        A name the user set is never replaced. Titling is a convenience, so a
        failure is logged and the session keeps its current name.
        """
        store = self._services.store
        if store.get_session(context.session_id).title != DEFAULT_SESSION_TITLE:
            return
        try:
            result = await self._services.gateway.chat(
                UTILITY_ROLE,
                [
                    {"role": "system", "content": self._prompts["title_instruction"]},
                    {"role": "user", "content": user_text[:TITLE_SOURCE_CHARACTERS]},
                ],
            )
        except OrchestratorError as error:
            logger.warning(
                "Session titling failed; name left unchanged",
                extra={"error_code": error.error_code},
            )
            return
        self._audit_model_call(UTILITY_ROLE, context.session_id, user_text, result)
        title = clean_title(result.text)
        if title:
            store.rename_session(context.session_id, title)

    async def _load_requested_skills(
        self, context: ToolContext, user_text: str
    ) -> None:
        """Load any skill the user named, before the model's first step.

        Relying on the model to call load_skill when asked is unreliable at
        this model size. The load goes through the router like any other
        call, so it is audited and shown as a tool card, and it is recorded
        in the conversation as a harness call so the model sees the skill.
        """
        for skill in self._services.skills.find_referenced(user_text):
            if skill.name in context.loaded_skill_names:
                continue
            call_id = f"harness_{uuid.uuid4().hex[:12]}"
            arguments_json = json.dumps({"name": skill.name})
            self._services.store.append_message(
                context.session_id,
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "load_skill",
                                "arguments": arguments_json,
                            },
                        }
                    ],
                },
                HARNESS_MODEL_ID,
            )
            outcome = await self._router.execute(
                context, call_id, "load_skill", arguments_json
            )
            self._services.store.append_message(
                context.session_id,
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": wrap_untrusted("load_skill", outcome.text),
                },
            )
            logger.info(
                "Skill loaded at the user's request", extra={"skill_name": skill.name}
            )

    def _finish_with_answer(self, context: ToolContext, result: ChatResult) -> str:
        """End the turn on a reply with no tool calls, if it says anything."""
        if not result.text.strip():
            # A small model can spend its whole output budget before writing
            # anything. Recording that as "answered" would hide the failure.
            self._emit_error(
                context,
                "MODEL_GAVE_NO_ANSWER",
                "The model stopped without writing an answer. Try again, or ask a "
                "narrower question.",
            )
            return DONE_ERROR
        self._persist_assistant(context, result)
        return DONE_ANSWERED

    async def _execute_tool_call(
        self,
        context: ToolContext,
        tool_call: ToolCallRequest,
        calls_made_this_turn: set[tuple[str, str]],
    ) -> bool:
        """Route one call and record its result. Returns True if it failed.

        An identical repeat of an earlier call in the same turn is not run
        again: small models loop on a call whose result they already have.
        """
        call_key = (tool_call.name, _normalise_arguments(tool_call.arguments_json))
        if call_key in calls_made_this_turn:
            result_text = REPEATED_CALL_MESSAGE.format(tool_name=tool_call.name)
            is_failed_call = True
            self._audit_repeated_call(context, tool_call)
        else:
            calls_made_this_turn.add(call_key)
            outcome = await self._router.execute(
                context, tool_call.call_id, tool_call.name, tool_call.arguments_json
            )
            result_text = outcome.text
            is_failed_call = outcome.is_malformed_call
        self._services.store.append_message(
            context.session_id,
            {
                "role": "tool",
                "tool_call_id": tool_call.call_id,
                "content": wrap_untrusted(tool_call.name, result_text),
            },
        )
        return is_failed_call

    def _audit_repeated_call(
        self, context: ToolContext, tool_call: ToolCallRequest
    ) -> None:
        self._services.audit_log.append(
            AuditRecord(
                kind="tool_call",
                session_id=context.session_id,
                model_id=context.model_id,
                tool_name=tool_call.name,
                input_hash=hash_content(tool_call.arguments_json),
                outcome="repeated",
                error_code="TOOL_CALL_REPEATED",
            )
        )

    @staticmethod
    def _emit_error(context: ToolContext, error_code: str, message: str) -> None:
        context.emit(
            AgentEvent(
                EventType.ERROR,
                {
                    "error": error_code,
                    "message": message,
                    "trace_id": correlation_id_var.get(),
                },
            )
        )

    async def _assemble_messages(self, context: ToolContext) -> list[Message]:
        # Only the fields the chat API defines: stored messages also carry
        # local metadata (model ID, turn duration) the model must not see.
        history = [
            {key: field for key, field in message.items() if key in CHAT_MESSAGE_FIELDS}
            for message in self._services.store.load_messages(context.session_id)
        ]
        conversation_text = " ".join(
            str(message.get("content") or "")
            for message in history
            if message.get("role") == "user"
        )
        system_prompt = build_system_prompt(
            self._prompts,
            self._services.skills.render_index(
                self._services.settings.context_budget.skill_index_max_tokens
            ),
            self._services.memory.select_for_prompt(conversation_text),
            context.allowlist.workspace,
            [str(root) for root in context.allowlist.allowed_roots[1:]],
        )
        if system_prompt.total_tokens > self._budget.system_tokens:
            logger.warning(
                "System prompt exceeds its share of the context window",
                extra={
                    "system_tokens": system_prompt.total_tokens,
                    "budget_tokens": self._budget.system_tokens,
                    "layer_tokens": system_prompt.layer_tokens,
                },
            )
        compacted_history = await compact_conversation(
            history, self._budget.conversation_tokens, self._summarise
        )
        return [{"role": "system", "content": system_prompt.text}, *compacted_history]

    async def _summarise(self, transcript: str) -> str:
        result = await self._services.gateway.chat(
            UTILITY_ROLE,
            [
                {"role": "system", "content": self._prompts["compaction_instruction"]},
                {"role": "user", "content": transcript},
            ],
        )
        self._audit_model_call(UTILITY_ROLE, "-", transcript, result)
        return result.text

    async def _call_model(
        self, context: ToolContext, messages: list[Message]
    ) -> ChatResult:
        registry = self._router.registry
        core_definitions = registry.core_definitions()
        core_names = {definition.name for definition in core_definitions}
        # A skill's allowed-tools may name a tool that is not registered (for
        # example an MCP connector that failed to start); skip it rather than
        # failing the turn.
        extra_definitions = [
            definition
            for name in sorted(context.discovered_tool_names - core_names)
            if (definition := registry.find(name)) is not None
        ]
        definitions = core_definitions + extra_definitions
        tools = [definition.to_openai_tool() for definition in definitions]

        def emit_text_delta(text: str) -> None:
            context.emit(AgentEvent(EventType.TEXT_DELTA, {"text": text}))

        result = await self._services.gateway.chat(
            ORCHESTRATOR_ROLE, messages, tools, emit_text_delta
        )
        context.model_id = result.model_id
        self._audit_model_call(ORCHESTRATOR_ROLE, context.session_id, messages, result)
        seconds = max(result.duration_ms / 1000, 0.001)
        context.emit(
            AgentEvent(
                EventType.USAGE,
                {
                    "model_id": result.model_id,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "duration_ms": result.duration_ms,
                    "tokens_per_second": round(result.completion_tokens / seconds, 1),
                    "context_used_tokens": estimate_tokens(str(messages[0]["content"]))
                    + conversation_tokens(messages)
                    + estimate_tokens(str(tools)),
                    "context_limit_tokens": self._context_limit_tokens,
                },
            )
        )
        return result

    def _persist_assistant(self, context: ToolContext, result: ChatResult) -> None:
        assistant_message: Message = {"role": "assistant", "content": result.text}
        if result.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tool_call.call_id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": tool_call.arguments_json,
                    },
                }
                for tool_call in result.tool_calls
            ]
        self._services.store.append_message(
            context.session_id, assistant_message, result.model_id
        )

    def _audit_model_call(
        self, role: str, session_id: str, model_input: object, result: ChatResult
    ) -> None:
        self._services.audit_log.append(
            AuditRecord(
                kind="model_call",
                session_id=session_id,
                model_id=result.model_id,
                role=role,
                input_hash=hash_content(model_input),
                result_hash=hash_content(
                    [result.text, [call.arguments_json for call in result.tool_calls]]
                ),
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                duration_ms=result.duration_ms,
            )
        )
