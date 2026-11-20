"""Context budgeting for a small window (plan section 7, step 5).

The HTTP API is stateless, so the whole history is resent on every call. With
a 16K window that history has to be kept inside a fixed share, tool results
have to be truncated, and older turns have to be compacted into a summary.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from orchestrator.settings import ContextBudgetSettings

# No local tokenizer is loaded in the orchestrator process. Four characters
# per token is the usual approximation for English prose; it over-counts code
# slightly, which errs on the safe side of the budget.
CHARACTERS_PER_TOKEN = 4

# Turns kept verbatim at the end of the conversation when compacting, so the
# model still sees its most recent tool results exactly.
RECENT_MESSAGES_KEPT = 6

Message = dict[str, object]
SummariseFunction = Callable[[str], Awaitable[str]]


def estimate_tokens(text: str) -> int:
    """Approximate the token count of a string."""
    return (len(text) + CHARACTERS_PER_TOKEN - 1) // CHARACTERS_PER_TOKEN


def estimate_message_tokens(message: Message) -> int:
    """Approximate the token count of one chat message, including tool calls."""
    content_tokens = estimate_tokens(str(message.get("content") or ""))
    tool_call_tokens = estimate_tokens(str(message.get("tool_calls") or ""))
    return content_tokens + tool_call_tokens


@dataclass(frozen=True)
class ContextBudget:
    """Token allowance for each prompt layer."""

    system_tokens: int
    tools_and_skills_tokens: int
    conversation_tokens: int
    output_tokens: int

    @classmethod
    def from_settings(
        cls, context_limit_tokens: int, shares: ContextBudgetSettings
    ) -> ContextBudget:
        """Split a context window by the configured shares."""
        return cls(
            system_tokens=int(context_limit_tokens * shares.system_share),
            tools_and_skills_tokens=int(
                context_limit_tokens * shares.tools_and_skills_share
            ),
            conversation_tokens=int(context_limit_tokens * shares.conversation_share),
            output_tokens=int(context_limit_tokens * shares.output_share),
        )


def truncate_tool_result(
    result_text: str, max_tokens: int, file_reference: str = ""
) -> str:
    """Keep the head and tail of an oversized tool result.

    Args:
        result_text: The full tool output.
        max_tokens: The allowance for one tool result.
        file_reference: Where the full output can be re-read, if anywhere.

    Returns:
        The text unchanged when it fits, otherwise head, a marker naming how
        much was removed and where the rest is, then tail.
    """
    if estimate_tokens(result_text) <= max_tokens:
        return result_text
    max_characters = max_tokens * CHARACTERS_PER_TOKEN
    head_characters = int(max_characters * 0.7)
    tail_characters = max_characters - head_characters
    omitted_characters = len(result_text) - max_characters
    reference_note = f" Full content: {file_reference}." if file_reference else ""
    marker = (
        f"\n[... {omitted_characters} characters omitted.{reference_note} "
        "Read a narrower range if you need the middle ...]\n"
    )
    return result_text[:head_characters] + marker + result_text[-tail_characters:]


def conversation_tokens(messages: list[Message]) -> int:
    """Total estimated tokens across non-system messages."""
    return sum(
        estimate_message_tokens(message)
        for message in messages
        if message.get("role") != "system"
    )


def _split_for_compaction(
    messages: list[Message],
) -> tuple[list[Message], list[Message]]:
    """Split into (older, recent) without separating a tool call from its result."""
    split_index = max(0, len(messages) - RECENT_MESSAGES_KEPT)
    # A "tool" message is only valid directly after the assistant message that
    # requested it. Move the boundary back until the recent part starts cleanly.
    while split_index > 0 and messages[split_index].get("role") == "tool":
        split_index -= 1
    return messages[:split_index], messages[split_index:]


def _render_transcript(messages: list[Message]) -> str:
    lines = []
    for message in messages:
        content = str(message.get("content") or "")
        if message.get("tool_calls"):
            content += f" [called tools: {message['tool_calls']}]"
        lines.append(f"{message.get('role')}: {content}")
    return "\n".join(lines)


async def compact_conversation(
    messages: list[Message],
    budget_tokens: int,
    summarise: SummariseFunction,
) -> list[Message]:
    """Replace older turns with a summary once the conversation share is passed.

    Args:
        messages: Conversation without the system message.
        budget_tokens: The conversation share of the window.
        summarise: Utility-model call that condenses a transcript.

    Returns:
        The messages unchanged if they fit. Otherwise one summary message
        followed by the most recent turns verbatim.
    """
    if conversation_tokens(messages) <= budget_tokens:
        return messages
    older_messages, recent_messages = _split_for_compaction(messages)
    if not older_messages:
        return messages
    summary = await summarise(_render_transcript(older_messages))
    summary_message: Message = {
        "role": "user",
        "content": f"[Summary of the earlier conversation]\n{summary}",
    }
    return [summary_message, *recent_messages]
