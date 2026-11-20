// Field names are snake_case on purpose: these shapes mirror docs/event-contract.md
// exactly, and that file is the contract shared with the orchestrator.

export type SandboxState = "ready" | "unavailable";

export interface Health {
  is_healthy: boolean;
  is_offline: boolean;
  sandbox_state: SandboxState;
  roles: Record<string, string>;
  context_limit_tokens: number;
}

export interface Session {
  session_id: string;
  title: string;
  workspace_path: string;
  created_at: string;
}

export type MessageRole = "user" | "assistant" | "tool";

export interface MessageToolCall {
  id: string;
  function: { name: string; arguments: string };
}

export interface Message {
  role: MessageRole;
  content: string;
  model_id: string;
  tool_calls?: MessageToolCall[];
  tool_call_id?: string;
  /** On the final assistant message of an answered turn. */
  turn_duration_ms?: number;
}

export interface WorkspaceFile {
  relative_path: string;
  size_bytes: number;
  modified_at: string;
  is_changed_this_session: boolean;
  preview_path: string | null;
}

export interface Skill {
  name: string;
  description: string;
}

export interface MemoryFile {
  name: string;
  description: string;
  content: string;
}

export type IndexingState = "not_indexed" | "scanning" | "indexing" | "done" | "failed";

/** Progress of one connected folder's knowledge indexing, from /api/knowledge/status. */
export interface FolderIndexStatus {
  folder: string;
  state: IndexingState;
  total_file_count?: number;
  processed_file_count?: number;
  indexed_file_count?: number;
  unchanged_file_count?: number;
  skipped_online_only_count?: number;
  failed_file_count?: number;
  chunk_count?: number;
  failures?: string[];
  error_message?: string;
}

export type ApprovalDecision = "allow_once" | "allow_session" | "deny";

export type ToolOutcome = "ok" | "error" | "denied";

export type TaskStatus = "pending" | "in_progress" | "done";

export interface Task {
  id: number;
  title: string;
  status: TaskStatus;
}

export type ArtefactKind = "html" | "svg" | "markdown" | "docx" | "pptx" | "xlsx" | "pdf" | "text";

export type DoneReason = "answered" | "step_limit" | "cancelled" | "error";

export interface TextDeltaPayload {
  text: string;
}

export interface ToolCallPayload {
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  tier: number;
  summary: string;
}

export interface ToolResultPayload {
  call_id: string;
  tool_name: string;
  outcome: ToolOutcome;
  result_preview: string;
  duration_ms: number;
}

export interface ApprovalRequestPayload {
  request_id: string;
  call_id: string;
  tool_name: string;
  tier: number;
  action: string;
  target: string;
}

export interface QuestionPayload {
  question_id: string;
  question: string;
  options: string[];
}

export interface TaskUpdatePayload {
  tasks: Task[];
}

export interface ArtefactPayload {
  relative_path: string;
  kind: ArtefactKind;
  preview_path: string | null;
}

export interface UsagePayload {
  model_id: string;
  prompt_tokens: number;
  completion_tokens: number;
  duration_ms: number;
  tokens_per_second: number;
  context_used_tokens: number;
  context_limit_tokens: number;
}

export interface ErrorPayload {
  error: string;
  message: string;
  trace_id: string;
}

export interface DonePayload {
  reason: DoneReason;
  model_id: string;
  /** Milliseconds from the orchestrator receiving the message to the turn ending. */
  duration_ms?: number;
}

/** One file a knowledge search drew passages from, in rank order. */
export interface AccessedFile {
  file_path: string;
  passage_count: number;
  best_score: number;
}

export interface KnowledgeAccessPayload {
  query: string;
  files: AccessedFile[];
}

/** One indexed file in the index map. `id` is its absolute path. */
export interface KnowledgeNode {
  id: string;
  name: string;
  chunk_count: number;
}

/** Two files whose content is close in the index (cosine similarity). */
export interface KnowledgeEdge {
  source: string;
  target: string;
  similarity: number;
}

/** From /api/knowledge/graph. Nodes arrive ordered for a circular layout. */
export interface KnowledgeGraph {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  file_count: number;
  chunk_count: number;
}

export type StreamEvent =
  | { type: "text_delta"; payload: TextDeltaPayload }
  | { type: "tool_call"; payload: ToolCallPayload }
  | { type: "tool_result"; payload: ToolResultPayload }
  | { type: "approval_request"; payload: ApprovalRequestPayload }
  | { type: "question"; payload: QuestionPayload }
  | { type: "task_update"; payload: TaskUpdatePayload }
  | { type: "artefact"; payload: ArtefactPayload }
  | { type: "usage"; payload: UsagePayload }
  | { type: "knowledge_access"; payload: KnowledgeAccessPayload }
  | { type: "error"; payload: ErrorPayload }
  | { type: "done"; payload: DonePayload };

export type StreamEventType = StreamEvent["type"];

/** Every event name the orchestrator emits, in contract order. */
export const STREAM_EVENT_TYPES: readonly StreamEventType[] = [
  "text_delta",
  "tool_call",
  "tool_result",
  "approval_request",
  "question",
  "task_update",
  "artefact",
  "usage",
  "knowledge_access",
  "error",
  "done",
];
