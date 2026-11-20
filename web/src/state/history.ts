import type { Message, MessageToolCall } from "../api/types";
import type { TimelineItemDraft } from "./session-state";

const parseArguments = (rawArguments: string): Record<string, unknown> => {
  try {
    const decoded: unknown = JSON.parse(rawArguments);
    if (typeof decoded === "object" && decoded !== null && !Array.isArray(decoded)) {
      return decoded as Record<string, unknown>;
    }
  } catch {
    // Stored arguments are model output and may not be valid JSON; show them raw.
  }
  return { raw: rawArguments };
};

const toToolCallDraft = (
  call: MessageToolCall,
  resultsByCallId: Map<string, string>
): TimelineItemDraft => ({
  kind: "tool_call",
  callId: call.id,
  toolName: call.function.name,
  arguments: parseArguments(call.function.arguments),
  tier: null,
  summary: "",
  status: "recorded",
  resultPreview: resultsByCallId.get(call.id) ?? "",
  durationMs: null,
});

const toDrafts = (message: Message, resultsByCallId: Map<string, string>): TimelineItemDraft[] => {
  if (message.role === "user") {
    return [{ kind: "user_message", text: message.content }];
  }
  if (message.role === "tool") {
    return [];
  }
  const drafts: TimelineItemDraft[] = [];
  if (message.content.length > 0) {
    drafts.push({
      kind: "assistant_text",
      text: message.content,
      modelId: message.model_id,
      isStreaming: false,
      turnDurationMs: message.turn_duration_ms,
    });
  }
  const toolCalls = message.tool_calls ?? [];
  return drafts.concat(toolCalls.map((call) => toToolCallDraft(call, resultsByCallId)));
};

/**
 * Converts stored messages into timeline items. Tool-role messages are folded
 * into the card of the call they answer rather than shown on their own.
 *
 * @param messages - Messages as returned by `GET /api/sessions/{id}/messages`
 * @returns Timeline item drafts in conversation order; empty for no messages
 */
export function messagesToDrafts(messages: Message[]): TimelineItemDraft[] {
  const resultsByCallId = new Map<string, string>();
  for (const message of messages) {
    if (message.role === "tool" && message.tool_call_id !== undefined) {
      resultsByCallId.set(message.tool_call_id, message.content);
    }
  }
  return messages.flatMap((message) => toDrafts(message, resultsByCallId));
}
