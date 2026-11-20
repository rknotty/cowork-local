import { describe, expect, it } from "vitest";
import { parseStreamEvent } from "./event-parser";
import type { StreamEventType } from "./types";

const VALID_PAYLOADS: Record<StreamEventType, unknown> = {
  text_delta: { text: "Hello" },
  tool_call: { call_id: "c1", tool_name: "read_file", arguments: {}, tier: 0, summary: "Read" },
  tool_result: {
    call_id: "c1",
    tool_name: "read_file",
    outcome: "denied",
    result_preview: "",
    duration_ms: 3,
  },
  approval_request: {
    request_id: "r1",
    call_id: "c1",
    tool_name: "write_file",
    tier: 2,
    action: "Write",
    target: "a.txt",
  },
  question: { question_id: "q1", question: "Which?", options: ["A", "B"] },
  task_update: { tasks: [{ id: 1, title: "Plan", status: "in_progress" }] },
  artefact: { relative_path: "a.svg", kind: "svg", preview_path: null },
  usage: {
    model_id: "m:1",
    prompt_tokens: 1,
    completion_tokens: 2,
    duration_ms: 3,
    tokens_per_second: 4.5,
    context_used_tokens: 3,
    context_limit_tokens: 100,
  },
  knowledge_access: {
    query: "annual leave",
    files: [{ file_path: "C:\\docs\\leave.md", passage_count: 2, best_score: 0.03 }],
  },
  error: { error: "E", message: "Failed.", trace_id: "t1" },
  done: { reason: "answered", model_id: "m:1", duration_ms: 1200 },
};

const EVENT_TYPES = Object.keys(VALID_PAYLOADS) as StreamEventType[];

describe("parseStreamEvent", () => {
  it.each(EVENT_TYPES)("should accept a contract-shaped %s payload", (type) => {
    const payload = VALID_PAYLOADS[type];

    const parsed = parseStreamEvent(type, JSON.stringify(payload));

    expect(parsed).toEqual({ type, payload });
  });

  it.each(EVENT_TYPES)("should reject an empty object as a %s payload", (type) => {
    expect(parseStreamEvent(type, "{}")).toBeNull();
  });

  it("should reject data that is not valid JSON", () => {
    expect(parseStreamEvent("text_delta", "{not json")).toBeNull();
  });

  it("should reject a payload that is not an object", () => {
    expect(parseStreamEvent("text_delta", '"just a string"')).toBeNull();
  });

  it.each([
    ["tool_result", { ...(VALID_PAYLOADS.tool_result as object), outcome: "maybe" }],
    ["artefact", { ...(VALID_PAYLOADS.artefact as object), kind: "exe" }],
    ["done", { reason: "bored", model_id: "m:1" }],
    ["task_update", { tasks: [{ id: 1, title: "Plan", status: "paused" }] }],
    ["question", { question_id: "q1", question: "Which?", options: [1, 2] }],
    ["knowledge_access", { query: "x", files: [{ file_path: "a.md", passage_count: "two" }] }],
    ["done", { reason: "answered", model_id: "m:1", duration_ms: "slow" }],
  ] as const)("should reject a %s payload with a value outside the contract", (type, payload) => {
    expect(parseStreamEvent(type, JSON.stringify(payload))).toBeNull();
  });
});
