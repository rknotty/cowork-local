"""Model gateway: the single module every other component calls for inference.

Nothing else in the codebase knows Foundry Local exists. The gateway exposes
four functions (chat, embed, transcribe, health), binds each call to a role
from `config/roles.yaml`, and returns token usage and latency for the audit
log.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from openai.types import CreateEmbeddingResponse

from orchestrator.context_budget import estimate_tokens
from orchestrator.errors import GatewayRequestError, GatewayUnavailableError
from orchestrator.model_runtime import ModelRuntimeProtocol, ResolvedModel
from orchestrator.settings import RoleSettings, Settings

logger = logging.getLogger(__name__)

# Limits documented for ONNX embedding requests on the equivalent Azure Local
# service. Assumed to apply here too (plan section 12, step 3).
EMBEDDING_BATCH_SIZE = 32
EMBEDDING_MAX_CHARACTERS = 8192
# Each request is also capped by size. Spreadsheet text runs at about 1.3
# characters per token (prose about 6), so 32 spreadsheet passages made one
# 51,000-token request. Foundry keeps the working memory of its largest request,
# and on this shared-memory device that pushed the model weights into the page
# file. Embedding time is linear in tokens, so smaller requests cost nothing in
# throughput. 16,000 characters is at most about 12,000 tokens.
EMBEDDING_BATCH_MAX_CHARACTERS = 16_000
# A healthy 12,000-token request takes about 6 s. Two minutes means the service
# is stalled; failing then beats waiting through the chat timeout (5 minutes,
# retried twice).
EMBEDDING_REQUEST_TIMEOUT_SECONDS = 120.0

# The OpenAI client insists on a key. Foundry Local ignores it; this value is
# a placeholder, not a credential.
PLACEHOLDER_API_KEY = "local-no-key-required"

# Bounded, with the client's built-in exponential back-off. Inference calls
# have no side effects, so retrying a dropped connection is safe.
MAX_CONNECTION_RETRIES = 2

# After the daemon dies, an embedding batch is retried once on a restarted
# service so a long indexing run survives. Chat is not retried: its text has
# already streamed to the user.
EMBEDDING_RECOVERY_ATTEMPTS = 1

# A daemon that crashes again straight after a restart is not restarted in a
# loop; the failure is reported instead.
SERVICE_RESTART_COOLDOWN_SECONDS = 60.0

THINK_OPEN_TAG = "<think>"
THINK_CLOSE_TAG = "</think>"
_TEXT_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL
)

TextDeltaHandler = Callable[[str], None]


@dataclass(frozen=True)
class ToolCallRequest:
    """A tool call as the model emitted it. Arguments are unparsed JSON text."""

    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class ChatResult:
    """Outcome of one chat completion."""

    text: str
    tool_calls: list[ToolCallRequest]
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int
    finish_reason: str


@dataclass(frozen=True)
class EmbeddingResult:
    """Vectors for a batch of texts, in input order."""

    vectors: list[list[float]]
    model_id: str
    prompt_tokens: int
    duration_ms: int


@dataclass(frozen=True)
class TranscriptionResult:
    """Transcript of one audio file."""

    text: str
    model_id: str
    duration_ms: int


class ReasoningFilter:
    """Removes `<think>...</think>` spans from a streamed answer.

    Reasoning-capable local models emit their scratch work inline. It is not
    part of the answer, wastes the user's attention and must not be persisted
    into the conversation where it would consume the context budget.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._is_inside_reasoning = False

    def feed(self, chunk: str) -> str:
        """Return the visible part of a chunk, holding back partial tags."""
        self._pending += chunk
        visible_parts: list[str] = []
        while self._pending:
            tag = THINK_CLOSE_TAG if self._is_inside_reasoning else THINK_OPEN_TAG
            tag_index = self._pending.find(tag)
            if tag_index >= 0:
                if not self._is_inside_reasoning:
                    visible_parts.append(self._pending[:tag_index])
                self._pending = self._pending[tag_index + len(tag) :]
                self._is_inside_reasoning = not self._is_inside_reasoning
                continue
            held_back = self._partial_tag_length(tag)
            emit_until = len(self._pending) - held_back
            if not self._is_inside_reasoning:
                visible_parts.append(self._pending[:emit_until])
            self._pending = self._pending[emit_until:]
            break
        return "".join(visible_parts)

    def _partial_tag_length(self, tag: str) -> int:
        """Length of the longest tag prefix the pending text ends with."""
        for length in range(min(len(tag) - 1, len(self._pending)), 0, -1):
            if self._pending.endswith(tag[:length]):
                return length
        return 0


def extract_text_tool_calls(text: str) -> tuple[str, list[ToolCallRequest]]:
    """Recover tool calls a model wrote into its text instead of the API field.

    Some local chat templates emit `<tool_call>{...}</tool_call>` in content
    when the server does not parse it. Returns the text with those blocks
    removed and the recovered calls. Malformed blocks are left for the agent
    loop's repair step to report.
    """
    recovered_calls: list[ToolCallRequest] = []
    for index, match in enumerate(_TEXT_TOOL_CALL_PATTERN.finditer(text)):
        try:
            block = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(block, dict) or "name" not in block:
            continue
        arguments = block.get("arguments", {})
        recovered_calls.append(
            ToolCallRequest(
                call_id=f"text_call_{index}",
                name=str(block["name"]),
                arguments_json=(
                    arguments if isinstance(arguments, str) else json.dumps(arguments)
                ),
            )
        )
    if not recovered_calls:
        return text, []
    return _TEXT_TOOL_CALL_PATTERN.sub("", text).strip(), recovered_calls


def plan_embedding_batches(texts: list[str]) -> list[list[str]]:
    """Split texts into requests capped by count and by total characters.

    Each text is first truncated to the service's per-input limit. A single
    text longer than the character cap still gets a request of its own.
    """
    batches: list[list[str]] = []
    current: list[str] = []
    current_characters = 0
    for text in texts:
        truncated = text[:EMBEDDING_MAX_CHARACTERS]
        would_overflow = (
            current_characters + len(truncated) > EMBEDDING_BATCH_MAX_CHARACTERS
        )
        if current and (would_overflow or len(current) >= EMBEDDING_BATCH_SIZE):
            batches.append(current)
            current, current_characters = [], 0
        current.append(truncated)
        current_characters += len(truncated)
    if current:
        batches.append(current)
    return batches


@dataclass
class _StreamAccumulator:
    """Collects streamed deltas into one result."""

    text_parts: list[str] = field(default_factory=list)
    tool_call_parts: dict[int, dict[str, str]] = field(default_factory=dict)
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add_tool_call_delta(self, delta: Any) -> None:
        part = self.tool_call_parts.setdefault(
            delta.index, {"id": "", "name": "", "arguments": ""}
        )
        if delta.id:
            part["id"] = delta.id
        if delta.function and delta.function.name:
            part["name"] += delta.function.name
        if delta.function and delta.function.arguments:
            part["arguments"] += delta.function.arguments

    def tool_calls(self) -> list[ToolCallRequest]:
        return [
            ToolCallRequest(
                call_id=part["id"] or f"call_{index}",
                name=part["name"],
                arguments_json=part["arguments"] or "{}",
            )
            for index, part in sorted(self.tool_call_parts.items())
        ]


class ModelGateway:
    """Role-bound access to local inference."""

    def __init__(self, settings: Settings, runtime: ModelRuntimeProtocol) -> None:
        self._settings = settings
        self._runtime = runtime
        self._client: AsyncOpenAI | None = None
        self._endpoint = ""
        self._loaded_aliases: set[str] = set()
        # Foundry Local 0.14.0 crashed (access violation in the WebGPU
        # execution provider) when the chat model was loaded and called while
        # an embedding batch was running. Serialising every load and inference
        # call keeps one request on the GPU at a time. A chat call waits for
        # at most the embedding batch in flight; the lock is first-come,
        # first-served, so indexing cannot starve a conversation.
        self._inference_lock = asyncio.Lock()
        self._last_service_start = -SERVICE_RESTART_COOLDOWN_SECONDS

    def role_settings(self, role: str) -> RoleSettings:
        """Configuration bound to a role."""
        return self._settings.roles[role]

    def resolved_model(self, role: str) -> ResolvedModel:
        """The pinned model currently behind a role."""
        return self._runtime.resolve_model(self.role_settings(role).alias)

    async def chat(
        self,
        role: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        on_text_delta: TextDeltaHandler | None = None,
    ) -> ChatResult:
        """Run one chat completion against the model bound to `role`.

        The API is stateless: `messages` must be the full history.

        Args:
            role: "orchestrator" or "utility".
            messages: OpenAI-format messages.
            tools: OpenAI-format tool definitions. Tool choice is always
                "auto", the only mode rated reliable across local models.
            on_text_delta: Called with each visible text fragment as it
                arrives. Reasoning spans are filtered out first.

        Raises:
            GatewayUnavailableError: Foundry Local unreachable or timed out.
            GatewayRequestError: Foundry Local rejected the request.
        """
        role_settings = self.role_settings(role)
        async with self._inference_lock:
            client, model = await self._prepare(role_settings.alias)
            request = self._chat_request(model, role_settings, messages, tools)
            started_at = time.monotonic()
            accumulator = await self._stream_chat(client, request, on_text_delta)
            duration_ms = int((time.monotonic() - started_at) * 1000)
        text, text_tool_calls = extract_text_tool_calls(
            "".join(accumulator.text_parts).strip()
        )
        tool_calls = accumulator.tool_calls() or text_tool_calls
        return ChatResult(
            text=text,
            tool_calls=tool_calls,
            model_id=model.model_id,
            prompt_tokens=accumulator.prompt_tokens
            or sum(estimate_tokens(str(message)) for message in messages),
            completion_tokens=accumulator.completion_tokens or estimate_tokens(text),
            duration_ms=duration_ms,
            finish_reason=accumulator.finish_reason,
        )

    @staticmethod
    def _chat_request(
        model: ResolvedModel,
        role_settings: RoleSettings,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": model.model_id,
            "messages": messages,
            "temperature": role_settings.temperature,
            "max_tokens": role_settings.max_output_tokens,
            "stream": True,
        }
        if tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"
        if role_settings.is_thinking_enabled is not None:
            # Passed to the model's chat template. Foundry Local honours it for
            # Qwen3; a template that ignores it is unaffected.
            request["extra_body"] = {
                "chat_template_kwargs": {
                    "enable_thinking": role_settings.is_thinking_enabled
                }
            }
        return request

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed texts with the embeddings role, batching to the service limits.

        Each batch takes the inference lock separately, so a chat call can run
        between the batches of a long document.

        Raises:
            GatewayUnavailableError: The service failed and did not recover.
            GatewayRequestError: The service rejected a batch.
        """
        alias = self.role_settings("embeddings").alias
        started_at = time.monotonic()
        vectors: list[list[float]] = []
        prompt_tokens = 0
        model_id = ""
        for batch in plan_embedding_batches(texts):
            response, model_id = await self._embed_batch(alias, batch)
            vectors.extend(item.embedding for item in response.data)
            if response.usage:
                prompt_tokens += response.usage.prompt_tokens
        if not model_id:
            # No texts, so no call was made; the ID is still worth reporting.
            model_id = (
                await asyncio.to_thread(self.resolved_model, "embeddings")
            ).model_id
        return EmbeddingResult(
            vectors=vectors,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        """Transcribe an audio file, loading the speech model only for the call.

        Speech shares the memory pool with the orchestrator model, so it is
        unloaded straight after use (plan section 4).

        Goes through the runtime rather than the HTTP API: the daemon in
        Foundry Local CLI 0.14.0 rejects the documented multipart request to
        /v1/audio/transcriptions (docs/phase-0-findings.md).
        """
        alias = self.role_settings("speech").alias
        started_at = time.monotonic()
        async with self._inference_lock:
            try:
                text, model_id = await asyncio.to_thread(
                    self._runtime.transcribe_file, alias, audio_path
                )
            finally:
                await asyncio.to_thread(self._runtime.unload_model, alias)
                self._loaded_aliases.discard(alias)
        return TranscriptionResult(
            text=text,
            model_id=model_id,
            duration_ms=int((time.monotonic() - started_at) * 1000),
        )

    async def health(self) -> dict[str, object]:
        """Report whether the local service answers, and which models are bound.

        Never raises: an unreachable service is reported as `is_healthy: False`
        so the interface can show the state instead of failing.
        """
        started_at = time.monotonic()
        try:
            # A CLI call: off the event loop, which the interface polls.
            endpoint = await asyncio.to_thread(self._runtime.resolve_endpoint)
            async with httpx.AsyncClient(
                timeout=self._settings.gateway.health_timeout_seconds
            ) as http_client:
                response = await http_client.get(f"{endpoint}/v1/models")
                response.raise_for_status()
        except (GatewayUnavailableError, GatewayRequestError, httpx.HTTPError) as exc:
            logger.warning(
                "Model service health check failed",
                extra={"exception_type": type(exc).__name__},
            )
            return {"is_healthy": False, "error_code": "MODEL_GATEWAY_UNAVAILABLE"}
        roles = await asyncio.to_thread(
            lambda: {
                role: self.resolved_model(role).model_id
                for role in self._settings.roles
            }
        )
        return {
            "is_healthy": True,
            "endpoint": endpoint,
            "duration_ms": int((time.monotonic() - started_at) * 1000),
            "roles": roles,
        }

    async def _embed_batch(
        self, alias: str, batch: list[str]
    ) -> tuple[CreateEmbeddingResponse, str]:
        """Embed one batch, recovering once if the service has gone away.

        Returns:
            The service response and the model ID that produced it.
        """
        last_error: Exception | None = None
        for attempt in range(1 + EMBEDDING_RECOVERY_ATTEMPTS):
            async with self._inference_lock:
                client, model = await self._prepare(alias)
                try:
                    response = await client.embeddings.create(
                        model=model.model_id,
                        input=batch,
                        timeout=EMBEDDING_REQUEST_TIMEOUT_SECONDS,
                    )
                except (APIConnectionError, APITimeoutError) as exc:
                    self._reset_connection()
                    last_error = exc
                    logger.warning(
                        "Embedding batch failed; recovering",
                        extra={"attempt": attempt + 1, "batch_size": len(batch)},
                    )
                    continue
                except APIStatusError as exc:
                    raise GatewayRequestError(
                        "embedding call rejected", status_code=exc.status_code
                    ) from exc
                return response, model.model_id
        raise GatewayUnavailableError("embedding call failed") from last_error

    async def _stream_chat(
        self,
        client: AsyncOpenAI,
        request: dict[str, Any],
        on_text_delta: TextDeltaHandler | None,
    ) -> _StreamAccumulator:
        accumulator = _StreamAccumulator()
        reasoning_filter = ReasoningFilter()
        try:
            stream = await client.chat.completions.create(**request)
            async for chunk in stream:
                if chunk.usage:
                    accumulator.prompt_tokens = chunk.usage.prompt_tokens
                    accumulator.completion_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    accumulator.finish_reason = choice.finish_reason
                for tool_call_delta in choice.delta.tool_calls or []:
                    accumulator.add_tool_call_delta(tool_call_delta)
                visible_text = reasoning_filter.feed(choice.delta.content or "")
                if visible_text:
                    accumulator.text_parts.append(visible_text)
                    if on_text_delta:
                        on_text_delta(visible_text)
        except (APIConnectionError, APITimeoutError) as exc:
            self._reset_connection()
            raise GatewayUnavailableError("chat call failed") from exc
        except APIStatusError as exc:
            raise GatewayRequestError(
                "chat call rejected", status_code=exc.status_code
            ) from exc
        return accumulator

    def _reset_connection(self) -> None:
        """Forget the endpoint and load state after a connection failure.

        The Foundry daemon restarts on a new dynamic port with no models
        loaded, so a cached client would fail on every later call.
        """
        logger.warning("Model service connection lost; will re-resolve endpoint")
        self._client = None
        self._endpoint = ""
        self._loaded_aliases.clear()

    async def _prepare(self, alias: str) -> tuple[AsyncOpenAI, ResolvedModel]:
        """Connect, starting the service if it has stopped, and load a model.

        Call only while holding the inference lock. The runtime's CLI calls
        block for seconds, so they run in a worker thread to keep the API and
        the event stream responsive.
        """
        client = self._client
        if client is None:
            client = await asyncio.to_thread(self._connect)
        model = await asyncio.to_thread(self._runtime.resolve_model, alias)
        if alias not in self._loaded_aliases:
            await asyncio.to_thread(self._runtime.load_model, alias)
            self._loaded_aliases.add(alias)
        return client, model

    def _connect(self) -> AsyncOpenAI:
        """Resolve the endpoint and build a client; start the daemon if needed.

        Raises:
            GatewayUnavailableError: The service is down and was restarted
                too recently to try again, or did not come back.
        """
        try:
            endpoint = self._runtime.resolve_endpoint()
        except GatewayUnavailableError:
            if not self._may_start_service():
                raise
            logger.warning("Model service is not running; starting it")
            self._runtime.start_service()
            endpoint = self._runtime.resolve_endpoint()
        self._endpoint = endpoint
        self._client = AsyncOpenAI(
            base_url=f"{endpoint}/v1",
            api_key=PLACEHOLDER_API_KEY,
            timeout=self._settings.gateway.request_timeout_seconds,
            max_retries=MAX_CONNECTION_RETRIES,
        )
        return self._client

    def _may_start_service(self) -> bool:
        """True at most once per cooldown, so a crashing daemon is not looped."""
        now = time.monotonic()
        if now - self._last_service_start < SERVICE_RESTART_COOLDOWN_SECONDS:
            return False
        self._last_service_start = now
        return True
