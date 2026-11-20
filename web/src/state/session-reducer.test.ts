import { describe, expect, it } from "vitest";
import type { Message, StreamEvent } from "../api/types";
import { sessionReducer } from "./session-reducer";
import { INITIAL_SESSION_STATE } from "./session-state";
import type { SessionState } from "./session-state";

const applyEvents = (
  events: StreamEvent[],
  start: SessionState = INITIAL_SESSION_STATE
): SessionState =>
  events.reduce((state, event) => sessionReducer(state, { type: "stream_event", event }), start);

const textDelta = (text: string): StreamEvent => ({ type: "text_delta", payload: { text } });

const toolCall: StreamEvent = {
  type: "tool_call",
  payload: {
    call_id: "call-1",
    tool_name: "read_file",
    arguments: { path: "notes.txt" },
    tier: 1,
    summary: "Read notes.txt",
  },
};

const toolResult: StreamEvent = {
  type: "tool_result",
  payload: {
    call_id: "call-1",
    tool_name: "read_file",
    outcome: "ok",
    result_preview: "first line",
    duration_ms: 42,
  },
};

const done = (reason: "answered" | "step_limit" | "cancelled" | "error"): StreamEvent => ({
  type: "done",
  payload: { reason, model_id: "example-model-14b:2" },
});

describe("sessionReducer stream events", () => {
  it("should accumulate text_delta fragments into one streaming assistant item", () => {
    const state = applyEvents([textDelta("Hel"), textDelta("lo"), textDelta(" there")]);

    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      kind: "assistant_text",
      text: "Hello there",
      isStreaming: true,
      modelId: "",
    });
    expect(state.isTurnActive).toBe(true);
  });

  it("should start a new assistant item when text resumes after a tool call", () => {
    const state = applyEvents([textDelta("Before"), toolCall, textDelta("After")]);

    expect(state.items.map((item) => item.kind)).toEqual([
      "assistant_text",
      "tool_call",
      "assistant_text",
    ]);
    expect(state.items[0]).toMatchObject({ text: "Before", isStreaming: false });
    expect(state.items[2]).toMatchObject({ text: "After", isStreaming: true });
  });

  it("should add a running tool card on tool_call", () => {
    const state = applyEvents([toolCall]);

    expect(state.items[0]).toMatchObject({
      kind: "tool_call",
      callId: "call-1",
      toolName: "read_file",
      summary: "Read notes.txt",
      tier: 1,
      status: "running",
      durationMs: null,
    });
  });

  it("should complete the matching tool card on tool_result", () => {
    const state = applyEvents([toolCall, toolResult]);

    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      status: "ok",
      resultPreview: "first line",
      durationMs: 42,
      summary: "Read notes.txt",
    });
  });

  it("should still show a tool_result whose tool_call was never seen", () => {
    const state = applyEvents([toolResult]);

    expect(state.items[0]).toMatchObject({ kind: "tool_call", callId: "call-1", status: "ok" });
  });

  it("should add an undecided approval prompt on approval_request", () => {
    const state = applyEvents([
      {
        type: "approval_request",
        payload: {
          request_id: "req-1",
          call_id: "call-1",
          tool_name: "write_file",
          tier: 2,
          action: "Write file",
          target: "C:\\Projects\\out.txt",
        },
      },
    ]);

    expect(state.items[0]).toMatchObject({
      kind: "approval",
      requestId: "req-1",
      tier: 2,
      action: "Write file",
      target: "C:\\Projects\\out.txt",
      decision: null,
    });
  });

  it("should add an unanswered question card on question", () => {
    const state = applyEvents([
      {
        type: "question",
        payload: { question_id: "q-1", question: "Which format?", options: ["PDF", "Word"] },
      },
    ]);

    expect(state.items[0]).toMatchObject({
      kind: "question",
      questionId: "q-1",
      options: ["PDF", "Word"],
      answer: null,
    });
  });

  it("should replace the whole task list on task_update", () => {
    const first: StreamEvent = {
      type: "task_update",
      payload: {
        tasks: [
          { id: 1, title: "Read input", status: "done" },
          { id: 2, title: "Draft report", status: "in_progress" },
        ],
      },
    };
    const second: StreamEvent = {
      type: "task_update",
      payload: { tasks: [{ id: 3, title: "Review", status: "pending" }] },
    };

    const state = applyEvents([first, second]);

    expect(state.tasks).toEqual([{ id: 3, title: "Review", status: "pending" }]);
  });

  it("should record and select an artefact, replacing an earlier entry for the same path", () => {
    const state = applyEvents([
      { type: "artefact", payload: { relative_path: "a.html", kind: "html", preview_path: null } },
      { type: "artefact", payload: { relative_path: "b.docx", kind: "docx", preview_path: null } },
      {
        type: "artefact",
        payload: { relative_path: "b.docx", kind: "docx", preview_path: "previews/b.pdf" },
      },
    ]);

    expect(state.artefacts).toHaveLength(2);
    expect(state.selectedArtefactPath).toBe("b.docx");
    expect(state.artefacts.find((artefact) => artefact.relative_path === "b.docx")).toMatchObject({
      preview_path: "previews/b.pdf",
    });
    expect(state.workspaceRevision).toBe(3);
  });

  it("should keep the latest usage payload on usage", () => {
    const state = applyEvents([
      {
        type: "usage",
        payload: {
          model_id: "example-model-14b:2",
          prompt_tokens: 100,
          completion_tokens: 50,
          duration_ms: 2000,
          tokens_per_second: 25,
          context_used_tokens: 150,
          context_limit_tokens: 32768,
        },
      },
    ]);

    expect(state.usage).toMatchObject({ tokens_per_second: 25, context_used_tokens: 150 });
  });

  it("should add an error item carrying message and trace ID on error", () => {
    const state = applyEvents([
      {
        type: "error",
        payload: { error: "MODEL_FAILED", message: "The model stopped.", trace_id: "trace-9" },
      },
    ]);

    expect(state.items[0]).toMatchObject({
      kind: "turn_error",
      message: "The model stopped.",
      traceId: "trace-9",
    });
  });

  it("should end the turn and attribute this turn's text to the model on done", () => {
    const afterUser = sessionReducer(INITIAL_SESSION_STATE, {
      type: "user_message_sent",
      text: "Hi",
    });

    const state = applyEvents([textDelta("Answer"), done("answered")], afterUser);

    expect(state.isTurnActive).toBe(false);
    expect(state.items[1]).toMatchObject({
      kind: "assistant_text",
      modelId: "example-model-14b:2",
      isStreaming: false,
    });
  });

  it("should not re-attribute text from an earlier turn on done", () => {
    const history: Message[] = [
      { role: "user", content: "First", model_id: "" },
      { role: "assistant", content: "Old answer", model_id: "older-model:1" },
    ];
    const loaded = sessionReducer(INITIAL_SESSION_STATE, {
      type: "history_loaded",
      messages: history,
    });
    const afterUser = sessionReducer(loaded, { type: "user_message_sent", text: "Second" });

    const state = applyEvents([textDelta("New answer"), done("answered")], afterUser);

    expect(state.items[1]).toMatchObject({ text: "Old answer", modelId: "older-model:1" });
    expect(state.items[3]).toMatchObject({ text: "New answer", modelId: "example-model-14b:2" });
  });

  it("should put the turn's response time on its final answer only", () => {
    const afterUser = sessionReducer(INITIAL_SESSION_STATE, {
      type: "user_message_sent",
      text: "Hi",
    });
    const timedDone: StreamEvent = {
      type: "done",
      payload: { reason: "answered", model_id: "example-model-14b:2", duration_ms: 12_400 },
    };

    const state = applyEvents(
      [textDelta("Planning"), toolCall, toolResult, textDelta("Final answer"), timedDone],
      afterUser
    );

    const answers = state.items.filter((item) => item.kind === "assistant_text");
    expect(answers[0]).not.toHaveProperty("turnDurationMs", 12_400);
    expect(answers[1]).toMatchObject({ text: "Final answer", turnDurationMs: 12_400 });
  });

  it("should not show a response time on a turn that did not answer", () => {
    const afterUser = sessionReducer(INITIAL_SESSION_STATE, {
      type: "user_message_sent",
      text: "Hi",
    });
    const stopped: StreamEvent = {
      type: "done",
      payload: { reason: "cancelled", model_id: "example-model-14b:2", duration_ms: 900 },
    };

    const state = applyEvents([textDelta("Partial"), stopped], afterUser);

    expect(state.items[1]).toMatchObject({ kind: "assistant_text", turnDurationMs: undefined });
  });

  it("should count every knowledge search so a repeated query replays", () => {
    const search: StreamEvent = {
      type: "knowledge_access",
      payload: { query: "leave", files: [] },
    };

    const state = applyEvents([search, search]);

    expect(state.knowledgeAccess).toEqual({ sequence: 2, payload: { query: "leave", files: [] } });
  });

  it("should restore the stored response time from history", () => {
    const history: Message[] = [
      { role: "user", content: "Q", model_id: "" },
      { role: "assistant", content: "A", model_id: "m:1", turn_duration_ms: 8_000 },
    ];

    const state = sessionReducer(INITIAL_SESSION_STATE, {
      type: "history_loaded",
      messages: history,
    });

    expect(state.items[1]).toMatchObject({ turnDurationMs: 8_000 });
  });

  it.each(["step_limit", "cancelled"] as const)(
    "should add a notice when done arrives with reason %s",
    (reason) => {
      const state = applyEvents([done(reason)]);

      expect(state.items.at(-1)).toMatchObject({ kind: "turn_notice", reason });
    }
  );

  it.each(["answered", "error"] as const)(
    "should not add a notice when done arrives with reason %s",
    (reason) => {
      const state = applyEvents([done(reason)]);

      expect(state.items).toHaveLength(0);
    }
  );
});

describe("sessionReducer local actions", () => {
  it("should append the user message and mark the turn active", () => {
    const state = sessionReducer(INITIAL_SESSION_STATE, { type: "user_message_sent", text: "Hi" });

    expect(state.items[0]).toMatchObject({ kind: "user_message", text: "Hi" });
    expect(state.isTurnActive).toBe(true);
  });

  it("should place loaded history before anything that already streamed in", () => {
    const streamed = applyEvents([textDelta("Live")]);

    const state = sessionReducer(streamed, {
      type: "history_loaded",
      messages: [{ role: "user", content: "Earlier", model_id: "" }],
    });

    expect(state.items.map((item) => item.kind)).toEqual(["user_message", "assistant_text"]);
    expect(new Set(state.items.map((item) => item.id)).size).toBe(2);
  });

  it("should record the decision on the matching approval only", () => {
    const pending = applyEvents([
      {
        type: "approval_request",
        payload: {
          request_id: "req-1",
          call_id: "c",
          tool_name: "t",
          tier: 2,
          action: "a",
          target: "x",
        },
      },
      {
        type: "approval_request",
        payload: {
          request_id: "req-2",
          call_id: "c",
          tool_name: "t",
          tier: 2,
          action: "a",
          target: "y",
        },
      },
    ]);

    const state = sessionReducer(pending, {
      type: "approval_decided",
      requestId: "req-2",
      decision: "deny",
    });

    expect(state.items[0]).toMatchObject({ decision: null });
    expect(state.items[1]).toMatchObject({ decision: "deny" });
  });

  it("should record the answer on the matching question", () => {
    const pending = applyEvents([
      { type: "question", payload: { question_id: "q-1", question: "Why?", options: [] } },
    ]);

    const state = sessionReducer(pending, {
      type: "question_answered",
      questionId: "q-1",
      answer: "Because",
    });

    expect(state.items[0]).toMatchObject({ answer: "Because" });
  });

  it("should remove a dismissed item", () => {
    const withError = applyEvents([
      { type: "error", payload: { error: "E", message: "Failed.", trace_id: "t" } },
    ]);
    const itemId = withError.items[0]?.id ?? "";

    const state = sessionReducer(withError, { type: "item_dismissed", itemId });

    expect(state.items).toHaveLength(0);
  });

  it("should select an artefact opened from the file list", () => {
    const state = sessionReducer(INITIAL_SESSION_STATE, {
      type: "artefact_opened",
      artefact: { relative_path: "notes.md", kind: "markdown", preview_path: null },
    });

    expect(state.selectedArtefactPath).toBe("notes.md");
    expect(state.artefacts).toHaveLength(1);
  });

  it("should bump the workspace revision on workspace_changed", () => {
    const state = sessionReducer(INITIAL_SESSION_STATE, { type: "workspace_changed" });

    expect(state.workspaceRevision).toBe(1);
  });
});
