import type {
  ApprovalDecision,
  ArtefactPayload,
  KnowledgeAccessPayload,
  Message,
  StreamEvent,
  Task,
  ToolOutcome,
  UsagePayload,
} from "../api/types";

/** "recorded" marks a call restored from history, where the outcome is not stored. */
export type ToolCallStatus = "running" | ToolOutcome | "recorded";

export interface UserMessageItem {
  kind: "user_message";
  id: string;
  text: string;
}

export interface AssistantTextItem {
  kind: "assistant_text";
  id: string;
  text: string;
  /** Empty until the turn's `done` event names the model that answered. */
  modelId: string;
  isStreaming: boolean;
  /** Total turn time, on the turn's final answer only, once it has finished. */
  turnDurationMs?: number;
}

export interface ToolCallItem {
  kind: "tool_call";
  id: string;
  callId: string;
  toolName: string;
  arguments: Record<string, unknown>;
  tier: number | null;
  summary: string;
  status: ToolCallStatus;
  resultPreview: string;
  durationMs: number | null;
}

export interface ApprovalItem {
  kind: "approval";
  id: string;
  requestId: string;
  callId: string;
  toolName: string;
  tier: number;
  action: string;
  target: string;
  decision: ApprovalDecision | null;
}

export interface QuestionItem {
  kind: "question";
  id: string;
  questionId: string;
  question: string;
  options: string[];
  answer: string | null;
}

export interface TurnErrorItem {
  kind: "turn_error";
  id: string;
  message: string;
  traceId: string;
}

export interface TurnNoticeItem {
  kind: "turn_notice";
  id: string;
  reason: "step_limit" | "cancelled";
}

export type TimelineItem =
  | UserMessageItem
  | AssistantTextItem
  | ToolCallItem
  | ApprovalItem
  | QuestionItem
  | TurnErrorItem
  | TurnNoticeItem;

/** A timeline item before the reducer has assigned its `id`. */
export type TimelineItemDraft =
  | Omit<UserMessageItem, "id">
  | Omit<AssistantTextItem, "id">
  | Omit<ToolCallItem, "id">
  | Omit<ApprovalItem, "id">
  | Omit<QuestionItem, "id">
  | Omit<TurnErrorItem, "id">
  | Omit<TurnNoticeItem, "id">;

export interface SessionState {
  items: TimelineItem[];
  tasks: Task[];
  artefacts: ArtefactPayload[];
  selectedArtefactPath: string | null;
  usage: UsagePayload | null;
  isTurnActive: boolean;
  nextItemNumber: number;
  /** Bumped whenever the workspace may have changed, so file lists refetch. */
  workspaceRevision: number;
  /**
   * The latest knowledge search. `sequence` increases with every search, even
   * a repeat of the same query, so the index map replays its animation.
   */
  knowledgeAccess: { sequence: number; payload: KnowledgeAccessPayload } | null;
}

export type SessionAction =
  | { type: "stream_event"; event: StreamEvent }
  | { type: "history_loaded"; messages: Message[] }
  | { type: "user_message_sent"; text: string }
  | { type: "approval_decided"; requestId: string; decision: ApprovalDecision }
  | { type: "question_answered"; questionId: string; answer: string }
  | { type: "item_dismissed"; itemId: string }
  | { type: "artefact_opened"; artefact: ArtefactPayload }
  | { type: "workspace_changed" };

/** The state of a session before any history or events have arrived. */
export const INITIAL_SESSION_STATE: SessionState = {
  items: [],
  tasks: [],
  artefacts: [],
  selectedArtefactPath: null,
  usage: null,
  isTurnActive: false,
  nextItemNumber: 1,
  workspaceRevision: 0,
  knowledgeAccess: null,
};
