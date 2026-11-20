import type {
  ApprovalRequestPayload,
  ArtefactPayload,
  DonePayload,
  QuestionPayload,
  StreamEvent,
  ToolCallPayload,
  ToolResultPayload,
} from "../api/types";
import { messagesToDrafts } from "./history";
import type { SessionAction, SessionState, TimelineItem, TimelineItemDraft } from "./session-state";

const closeStreaming = (item: TimelineItem): TimelineItem =>
  item.kind === "assistant_text" && item.isStreaming ? { ...item, isStreaming: false } : item;

const withIds = (drafts: TimelineItemDraft[], firstNumber: number): TimelineItem[] =>
  drafts.map((draft, offset) => ({ ...draft, id: `item-${firstNumber + offset}` }) as TimelineItem);

/** Appends one item; any text still streaming before it is closed off first. */
function appendItem(state: SessionState, draft: TimelineItemDraft): SessionState {
  const [item] = withIds([draft], state.nextItemNumber);
  if (item === undefined) {
    return state;
  }
  return {
    ...state,
    items: [...state.items.map(closeStreaming), item],
    nextItemNumber: state.nextItemNumber + 1,
  };
}

function applyTextDelta(state: SessionState, text: string): SessionState {
  const lastItem = state.items.at(-1);
  if (lastItem?.kind === "assistant_text" && lastItem.isStreaming) {
    const grown = { ...lastItem, text: lastItem.text + text };
    return { ...state, isTurnActive: true, items: [...state.items.slice(0, -1), grown] };
  }
  const draft: TimelineItemDraft = { kind: "assistant_text", text, modelId: "", isStreaming: true };
  return { ...appendItem(state, draft), isTurnActive: true };
}

function applyToolCall(state: SessionState, payload: ToolCallPayload): SessionState {
  return appendItem(state, {
    kind: "tool_call",
    callId: payload.call_id,
    toolName: payload.tool_name,
    arguments: payload.arguments,
    tier: payload.tier,
    summary: payload.summary,
    status: "running",
    resultPreview: "",
    durationMs: null,
  });
}

function applyToolResult(state: SessionState, payload: ToolResultPayload): SessionState {
  const result = {
    status: payload.outcome,
    resultPreview: payload.result_preview,
    durationMs: payload.duration_ms,
  };
  const hasCall = state.items.some(
    (item) => item.kind === "tool_call" && item.callId === payload.call_id
  );
  if (!hasCall) {
    // A result can arrive without its call when the stream reconnected mid-turn.
    return appendItem(state, {
      kind: "tool_call",
      callId: payload.call_id,
      toolName: payload.tool_name,
      arguments: {},
      tier: null,
      summary: "",
      ...result,
    });
  }
  const items = state.items.map((item) =>
    item.kind === "tool_call" && item.callId === payload.call_id ? { ...item, ...result } : item
  );
  return { ...state, items };
}

function upsertArtefact(state: SessionState, artefact: ArtefactPayload): SessionState {
  const others = state.artefacts.filter((known) => known.relative_path !== artefact.relative_path);
  return {
    ...state,
    artefacts: [...others, artefact],
    selectedArtefactPath: artefact.relative_path,
    workspaceRevision: state.workspaceRevision + 1,
  };
}

function applyDone(state: SessionState, payload: DonePayload): SessionState {
  const turnStart = state.items.findLastIndex((item) => item.kind === "user_message");
  const finalAnswerIndex =
    payload.reason === "answered"
      ? state.items.findLastIndex((item) => item.kind === "assistant_text")
      : -1;
  const items = state.items.map((item, index) => {
    if (item.kind !== "assistant_text") {
      return item;
    }
    const isUnattributed = index > turnStart && item.modelId === "";
    const isFinalAnswer = index === finalAnswerIndex && index > turnStart;
    return {
      ...item,
      isStreaming: false,
      modelId: isUnattributed ? payload.model_id : item.modelId,
      turnDurationMs: isFinalAnswer ? payload.duration_ms : item.turnDurationMs,
    };
  });
  const finished: SessionState = {
    ...state,
    items,
    isTurnActive: false,
    workspaceRevision: state.workspaceRevision + 1,
  };
  if (payload.reason === "step_limit" || payload.reason === "cancelled") {
    return appendItem(finished, { kind: "turn_notice", reason: payload.reason });
  }
  return finished;
}

const toApprovalDraft = (payload: ApprovalRequestPayload): TimelineItemDraft => ({
  kind: "approval",
  requestId: payload.request_id,
  callId: payload.call_id,
  toolName: payload.tool_name,
  tier: payload.tier,
  action: payload.action,
  target: payload.target,
  decision: null,
});

const toQuestionDraft = (payload: QuestionPayload): TimelineItemDraft => ({
  kind: "question",
  questionId: payload.question_id,
  question: payload.question,
  options: payload.options,
  answer: null,
});

function applyStreamEvent(state: SessionState, event: StreamEvent): SessionState {
  switch (event.type) {
    case "text_delta":
      return applyTextDelta(state, event.payload.text);
    case "tool_call":
      return { ...applyToolCall(state, event.payload), isTurnActive: true };
    case "tool_result":
      return applyToolResult(state, event.payload);
    case "approval_request":
      return appendItem(state, toApprovalDraft(event.payload));
    case "question":
      return appendItem(state, toQuestionDraft(event.payload));
    case "task_update":
      return { ...state, tasks: event.payload.tasks };
    case "artefact":
      return upsertArtefact(state, event.payload);
    case "usage":
      return { ...state, usage: event.payload };
    case "knowledge_access":
      return {
        ...state,
        knowledgeAccess: {
          sequence: (state.knowledgeAccess?.sequence ?? 0) + 1,
          payload: event.payload,
        },
      };
    case "error": {
      const { message, trace_id } = event.payload;
      return appendItem(state, { kind: "turn_error", message, traceId: trace_id });
    }
    case "done":
      return applyDone(state, event.payload);
    default: {
      const exhaustive: never = event;
      return exhaustive;
    }
  }
}

function applyHistory(state: SessionState, drafts: TimelineItemDraft[]): SessionState {
  const history = withIds(drafts, state.nextItemNumber);
  // History is fetched while the stream is already open, so anything that
  // streamed in meanwhile is newer and must stay after the stored messages.
  return {
    ...state,
    items: [...history, ...state.items],
    nextItemNumber: state.nextItemNumber + history.length,
  };
}

/**
 * Pure reducer for one session's view state. Stream events and local user
 * actions both pass through here; nothing else mutates the timeline.
 *
 * @param state - Current session state
 * @param action - A stream event or a local action
 * @returns The next state; the input is never mutated
 */
export function sessionReducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case "stream_event":
      return applyStreamEvent(state, action.event);
    case "history_loaded":
      return applyHistory(state, messagesToDrafts(action.messages));
    case "user_message_sent":
      return {
        ...appendItem(state, { kind: "user_message", text: action.text }),
        isTurnActive: true,
      };
    case "approval_decided": {
      const items = state.items.map((item) =>
        item.kind === "approval" && item.requestId === action.requestId
          ? { ...item, decision: action.decision }
          : item
      );
      return { ...state, items };
    }
    case "question_answered": {
      const items = state.items.map((item) =>
        item.kind === "question" && item.questionId === action.questionId
          ? { ...item, answer: action.answer }
          : item
      );
      return { ...state, items };
    }
    case "item_dismissed":
      return { ...state, items: state.items.filter((item) => item.id !== action.itemId) };
    case "artefact_opened":
      return upsertArtefact(state, action.artefact);
    case "workspace_changed":
      return { ...state, workspaceRevision: state.workspaceRevision + 1 };
    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}
