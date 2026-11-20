import type {
  ArtefactKind,
  DoneReason,
  StreamEvent,
  StreamEventType,
  Task,
  ToolOutcome,
} from "./types";

type Fields = Record<string, unknown>;

const ARTEFACT_KINDS: readonly string[] = [
  "html",
  "svg",
  "markdown",
  "docx",
  "pptx",
  "xlsx",
  "pdf",
  "text",
];
const TOOL_OUTCOMES: readonly string[] = ["ok", "error", "denied"];
const DONE_REASONS: readonly string[] = ["answered", "step_limit", "cancelled", "error"];
const TASK_STATUSES: readonly string[] = ["pending", "in_progress", "done"];

const isRecord = (candidate: unknown): candidate is Fields =>
  typeof candidate === "object" && candidate !== null && !Array.isArray(candidate);

const hasStrings = (fields: Fields, names: readonly string[]): boolean =>
  names.every((name) => typeof fields[name] === "string");

const hasNumbers = (fields: Fields, names: readonly string[]): boolean =>
  names.every((name) => typeof fields[name] === "number" && Number.isFinite(fields[name]));

const isAccessedFile = (candidate: unknown): boolean =>
  isRecord(candidate) &&
  hasStrings(candidate, ["file_path"]) &&
  hasNumbers(candidate, ["passage_count", "best_score"]);

const isTask = (candidate: unknown): candidate is Task =>
  isRecord(candidate) &&
  hasNumbers(candidate, ["id"]) &&
  hasStrings(candidate, ["title", "status"]) &&
  TASK_STATUSES.includes(candidate.status as string);

const isNullableString = (candidate: unknown): candidate is string | null =>
  candidate === null || typeof candidate === "string";

const isStringArray = (candidate: unknown): candidate is string[] =>
  Array.isArray(candidate) && candidate.every((entry) => typeof entry === "string");

function isValidToolPayload(type: "tool_call" | "tool_result", fields: Fields): boolean {
  if (!hasStrings(fields, ["call_id", "tool_name"])) {
    return false;
  }
  if (type === "tool_call") {
    return (
      isRecord(fields.arguments) && hasNumbers(fields, ["tier"]) && hasStrings(fields, ["summary"])
    );
  }
  return (
    hasStrings(fields, ["outcome", "result_preview"]) &&
    TOOL_OUTCOMES.includes(fields.outcome as ToolOutcome) &&
    hasNumbers(fields, ["duration_ms"])
  );
}

const USAGE_NUMBER_FIELDS = [
  "prompt_tokens",
  "completion_tokens",
  "duration_ms",
  "tokens_per_second",
  "context_used_tokens",
  "context_limit_tokens",
];

function isValidPayload(type: StreamEventType, fields: Fields): boolean {
  switch (type) {
    case "text_delta":
      return hasStrings(fields, ["text"]);
    case "tool_call":
    case "tool_result":
      return isValidToolPayload(type, fields);
    case "approval_request":
      return (
        hasStrings(fields, ["request_id", "call_id", "tool_name", "action", "target"]) &&
        hasNumbers(fields, ["tier"])
      );
    case "question":
      return hasStrings(fields, ["question_id", "question"]) && isStringArray(fields.options);
    case "task_update":
      return Array.isArray(fields.tasks) && fields.tasks.every(isTask);
    case "artefact":
      return (
        hasStrings(fields, ["relative_path", "kind"]) &&
        ARTEFACT_KINDS.includes(fields.kind as ArtefactKind) &&
        isNullableString(fields.preview_path)
      );
    case "usage":
      return hasStrings(fields, ["model_id"]) && hasNumbers(fields, USAGE_NUMBER_FIELDS);
    case "knowledge_access":
      return (
        hasStrings(fields, ["query"]) &&
        Array.isArray(fields.files) &&
        fields.files.every(isAccessedFile)
      );
    case "error":
      return hasStrings(fields, ["error", "message", "trace_id"]);
    case "done":
      return (
        hasStrings(fields, ["reason", "model_id"]) &&
        DONE_REASONS.includes(fields.reason as DoneReason) &&
        (fields.duration_ms === undefined || hasNumbers(fields, ["duration_ms"]))
      );
    default: {
      const exhaustive: never = type;
      return exhaustive;
    }
  }
}

/**
 * Validates one server-sent event frame against the contract.
 *
 * @param type - The frame's `event:` name
 * @param rawData - The frame's `data:` string, expected to be JSON
 * @returns A typed event, or null when the payload is not valid JSON or does not
 *   match the contract shape for that event name
 */
export function parseStreamEvent(type: StreamEventType, rawData: string): StreamEvent | null {
  let decoded: unknown;
  try {
    decoded = JSON.parse(rawData);
  } catch {
    // Malformed JSON is reported to the caller as null, the same as a bad shape.
    return null;
  }
  if (!isRecord(decoded) || !isValidPayload(type, decoded)) {
    return null;
  }
  // The shape was checked field by field above, so the assertion is sound.
  return { type, payload: decoded } as unknown as StreamEvent;
}
