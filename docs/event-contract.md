# Orchestrator API and event contract

The interface renders events and posts user actions. It makes no decisions.
The orchestrator serves this API on `127.0.0.1` only. All paths are under
`/api`. All bodies are JSON unless stated.

Change this file and `orchestrator/events.py` together.

## Errors

Every non-2xx response has this shape. No stack traces or internal detail.

```json
{ "error": "SESSION_NOT_FOUND", "message": "That session does not exist.", "trace_id": "abc123" }
```

## Endpoints

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| GET | `/api/health` | | `Health` |
| GET | `/api/sessions` | | `Session[]`, newest first |
| POST | `/api/sessions` | `{ "title"?: string }` | `Session` (201) |
| PATCH | `/api/sessions/{id}` | `{ "title": string }` (1 to 120 characters) | `Session`. Renames the session; whitespace is tidied, a blank name is refused with 400. A session still called "New session" is also named automatically after its first answered message; a name set here is never replaced |
| GET | `/api/sessions/{id}/messages` | | `Message[]` |
| POST | `/api/sessions/{id}/messages` | `{ "text": string }` | `{ "accepted": true }` (202). Output arrives on the event stream |
| GET | `/api/sessions/{id}/events` | | `text/event-stream`, see below |
| POST | `/api/sessions/{id}/approvals/{request_id}` | `{ "decision": "allow_once" \| "allow_session" \| "deny" }` | 204 |
| POST | `/api/sessions/{id}/answers/{question_id}` | `{ "answer": string }` | 204 |
| POST | `/api/sessions/{id}/stop` | | 204 |
| GET | `/api/sessions/{id}/files` | | `WorkspaceFile[]` |
| GET | `/api/sessions/{id}/files/{path}` | | Raw file bytes with a content type |
| PUT | `/api/sessions/{id}/files/{path}` | Raw file bytes | 204. Used for drag and drop |
| GET | `/api/skills` | | `Skill[]` |
| GET | `/api/memory` | | `MemoryFile[]` |
| PUT | `/api/memory/{name}` | `{ "description": string, "content": string }` | 204 |
| DELETE | `/api/memory/{name}` | | 204 |
| GET | `/api/folders` | | `{ "folders": string[] }` |
| PUT | `/api/folders` | `{ "folders": string[] }` | 204. Removes from the index every file not under a listed folder (cancelling any run in progress for it), then starts indexing each listed folder in the background |
| POST | `/api/folders/browse` | `{ "start_folder"?: string \| null }` (must be JSON) | `{ "folder": string \| null }`. Opens the Windows folder dialog on the orchestrator's desktop and returns the chosen folder, or null if cancelled. Not a connect: the caller still PUTs the folder list |
| GET | `/api/knowledge/status` | | `FolderIndexStatus[]`, one per connected folder |
| GET | `/api/knowledge/graph` | | `KnowledgeGraph`: the index as files and similarity links, for the index map |
| POST | `/api/knowledge/reindex` | | `{ "accepted": true }` (202). Re-indexes every connected folder; changed files only |
| POST | `/api/transcriptions` | Raw audio bytes, `Content-Type: audio/wav` or `audio/webm` | `{ "text": string }` |

## Types

```ts
interface Health {
  is_healthy: boolean;
  is_offline: boolean;            // true unless web search is enabled
  sandbox_state: "ready" | "unavailable";
  roles: Record<string, string>;  // role -> model ID with version, e.g. "qwen3-14b-generic-gpu:2"
  context_limit_tokens: number;
}

interface Session { session_id: string; title: string; workspace_path: string; created_at: string; }

interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  model_id: string;               // empty for user messages
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
  tool_call_id?: string;          // on role "tool"
}

interface WorkspaceFile {
  relative_path: string;
  size_bytes: number;
  modified_at: string;
  is_changed_this_session: boolean;
  preview_path: string | null;    // relative path of a PDF or PNG render, when one exists
}

interface FolderIndexStatus {
  folder: string;
  state: "not_indexed" | "scanning" | "indexing" | "done" | "failed";
  // Present once a run has started:
  total_file_count?: number;
  processed_file_count?: number;
  indexed_file_count?: number;       // newly indexed this run
  unchanged_file_count?: number;     // already indexed, content unchanged
  skipped_online_only_count?: number; // cloud placeholders, deliberately not downloaded
  failed_file_count?: number;
  chunk_count?: number;
  failures?: string[];               // "name: reason", at most 20
  error_message?: string;            // set when state is "failed"
}

// Each node is a file, placed by the mean embedding of its passages. Nodes
// arrive ordered so similar files are adjacent on a circle. Each file links
// to its three most similar files with cosine similarity of at least 0.2.
interface KnowledgeGraph {
  nodes: { id: string; name: string; chunk_count: number }[]; // id is the absolute path
  edges: { source: string; target: string; similarity: number }[];
  file_count: number;
  chunk_count: number;
}

interface Skill { name: string; description: string; }
interface MemoryFile { name: string; description: string; content: string; }
```

## Event stream

`GET /api/sessions/{id}/events` is a server-sent events stream. Each frame has
an `event:` name and a JSON `data:` payload. The stream stays open across
turns; one `done` event closes each turn.

| Event | Payload | Meaning |
| --- | --- | --- |
| `text_delta` | `{ "text": string }` | A fragment of the assistant's answer |
| `tool_call` | `{ "call_id", "tool_name", "arguments": object, "tier": 0-3, "summary": string }` | A tool call is starting |
| `tool_result` | `{ "call_id", "tool_name", "outcome": "ok" \| "error" \| "denied", "result_preview": string, "duration_ms": number }` | A tool call finished |
| `approval_request` | `{ "request_id", "call_id", "tool_name", "tier", "action": string, "target": string }` | The loop is blocked until `POST .../approvals/{request_id}` |
| `question` | `{ "question_id", "question": string, "options": string[] }` | The loop is blocked until `POST .../answers/{question_id}` |
| `task_update` | `{ "tasks": [{ "id": number, "title": string, "status": "pending" \| "in_progress" \| "done" }] }` | The full task list, replacing the previous one |
| `artefact` | `{ "relative_path": string, "kind": "html" \| "svg" \| "markdown" \| "docx" \| "pptx" \| "xlsx" \| "pdf" \| "text", "preview_path": string \| null }` | A file was created or changed in the workspace |
| `usage` | `{ "model_id", "prompt_tokens", "completion_tokens", "duration_ms", "tokens_per_second", "context_used_tokens", "context_limit_tokens" }` | Sent after each model call |
| `knowledge_access` | `{ "query": string, "files": [{ "file_path": string, "passage_count": number, "best_score": number }] }` | A knowledge search ran. `files` lists, in rank order, each file it drew passages from. Empty when nothing matched |
| `error` | `{ "error": string, "message": string, "trace_id": string }` | The turn failed. A `done` follows |
| `done` | `{ "reason": "answered" \| "step_limit" \| "cancelled" \| "error", "model_id": string, "duration_ms": number }` | The turn is over. `duration_ms` runs from the orchestrator receiving the message (including any wait for the GPU) to this event. On an answered turn it is also stored on the final assistant message as `turn_duration_ms` |
