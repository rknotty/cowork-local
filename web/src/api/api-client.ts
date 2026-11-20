import { ApiError, toApiError, toNetworkError } from "./api-error";
import type {
  ApprovalDecision,
  FolderIndexStatus,
  Health,
  KnowledgeGraph,
  MemoryFile,
  Message,
  Session,
  Skill,
  WorkspaceFile,
} from "./types";

const API_ROOT = "/api";
const DEFAULT_TIMEOUT_MS = 30_000;
// Uploads and speech-to-text run on local hardware and can legitimately be slow.
const SLOW_REQUEST_TIMEOUT_MS = 180_000;
const JSON_HEADERS = { "Content-Type": "application/json" };

interface RequestOptions {
  method?: string;
  body?: BodyInit;
  headers?: Record<string, string>;
  timeoutMs?: number;
}

const encodeSegment = (segment: string): string => encodeURIComponent(segment);

/**
 * Encodes a workspace-relative path for use in a URL, keeping `/` separators.
 *
 * @param relativePath - Path relative to the session workspace; `\` is treated as `/`
 * @returns The path with every segment percent-encoded
 */
export function encodeFilePath(relativePath: string): string {
  return relativePath
    .split(/[\\/]+/)
    .filter((segment) => segment.length > 0)
    .map(encodeSegment)
    .join("/");
}

/**
 * Builds the same-origin URL of a workspace file, for links, images and iframes.
 *
 * @param sessionId - The session that owns the workspace
 * @param relativePath - Path relative to the session workspace
 * @returns A relative `/api/...` URL
 */
export function buildFileUrl(sessionId: string, relativePath: string): string {
  return `${API_ROOT}/sessions/${encodeSegment(sessionId)}/files/${encodeFilePath(relativePath)}`;
}

/**
 * Builds the URL of a session's server-sent event stream.
 *
 * @param sessionId - The session to subscribe to
 * @returns A relative `/api/...` URL
 */
export function buildEventsUrl(sessionId: string): string {
  return `${API_ROOT}/sessions/${encodeSegment(sessionId)}/events`;
}

async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      method: options.method ?? "GET",
      body: options.body,
      headers: options.headers,
      signal: AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS),
    });
  } catch (cause) {
    throw toNetworkError(cause);
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return response;
}

async function sendForJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  try {
    return (await response.json()) as T;
  } catch (cause) {
    throw new ApiError(
      "UNEXPECTED_RESPONSE",
      "The orchestrator sent a response that could not be read.",
      "",
      response.status,
      cause
    );
  }
}

const postJson = (body: unknown): RequestOptions => ({
  method: "POST",
  body: JSON.stringify(body),
  headers: JSON_HEADERS,
});

const sessionPath = (sessionId: string): string => `/sessions/${encodeSegment(sessionId)}`;

/** Fetches orchestrator health. @throws {ApiError} On any failure. */
export function getHealth(): Promise<Health> {
  return sendForJson<Health>("/health");
}

/**
 * Renames a session.
 *
 * @param sessionId - The session to rename
 * @param title - The new name; the orchestrator tidies whitespace
 * @returns The renamed session
 * @throws {ApiError} On any failure, including a blank name
 */
export function renameSession(sessionId: string, title: string): Promise<Session> {
  return sendForJson<Session>(sessionPath(sessionId), {
    method: "PATCH",
    body: JSON.stringify({ title }),
    headers: JSON_HEADERS,
  });
}

/** Lists sessions, newest first. @throws {ApiError} On any failure. */
export function listSessions(): Promise<Session[]> {
  return sendForJson<Session[]>("/sessions");
}

/**
 * Creates a session.
 *
 * @param title - Optional title; the orchestrator picks one when omitted
 * @returns The created session
 * @throws {ApiError} On any failure
 */
export function createSession(title?: string): Promise<Session> {
  return sendForJson<Session>("/sessions", postJson(title === undefined ? {} : { title }));
}

/** Fetches a session's stored messages. @throws {ApiError} On any failure. */
export function listMessages(sessionId: string): Promise<Message[]> {
  return sendForJson<Message[]>(`${sessionPath(sessionId)}/messages`);
}

/**
 * Posts a user message. The answer arrives on the event stream, not here.
 *
 * @throws {ApiError} On any failure
 */
export async function postMessage(sessionId: string, text: string): Promise<void> {
  await send(`${sessionPath(sessionId)}/messages`, postJson({ text }));
}

/**
 * Posts the user's decision on an approval request.
 *
 * @throws {ApiError} On any failure
 */
export async function postApproval(
  sessionId: string,
  requestId: string,
  decision: ApprovalDecision
): Promise<void> {
  const path = `${sessionPath(sessionId)}/approvals/${encodeSegment(requestId)}`;
  await send(path, postJson({ decision }));
}

/**
 * Posts the user's answer to a question from the agent.
 *
 * @throws {ApiError} On any failure
 */
export async function postAnswer(
  sessionId: string,
  questionId: string,
  answer: string
): Promise<void> {
  const path = `${sessionPath(sessionId)}/answers/${encodeSegment(questionId)}`;
  await send(path, postJson({ answer }));
}

/** Asks the orchestrator to stop the current turn. @throws {ApiError} On any failure. */
export async function postStop(sessionId: string): Promise<void> {
  await send(`${sessionPath(sessionId)}/stop`, { method: "POST" });
}

/** Lists the files in a session workspace. @throws {ApiError} On any failure. */
export function listFiles(sessionId: string): Promise<WorkspaceFile[]> {
  return sendForJson<WorkspaceFile[]>(`${sessionPath(sessionId)}/files`);
}

/**
 * Reads a workspace file as text.
 *
 * @throws {ApiError} On any failure
 */
export async function getFileText(sessionId: string, relativePath: string): Promise<string> {
  const response = await send(`${sessionPath(sessionId)}/files/${encodeFilePath(relativePath)}`);
  return response.text();
}

/**
 * Uploads a file into the session workspace, replacing any file at that path.
 *
 * @throws {ApiError} On any failure
 */
export async function putFile(sessionId: string, relativePath: string, file: Blob): Promise<void> {
  await send(`${sessionPath(sessionId)}/files/${encodeFilePath(relativePath)}`, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": "application/octet-stream" },
    timeoutMs: SLOW_REQUEST_TIMEOUT_MS,
  });
}

/** Lists installed skills. @throws {ApiError} On any failure. */
export function listSkills(): Promise<Skill[]> {
  return sendForJson<Skill[]>("/skills");
}

/** Lists memory files. @throws {ApiError} On any failure. */
export function listMemory(): Promise<MemoryFile[]> {
  return sendForJson<MemoryFile[]>("/memory");
}

/**
 * Creates or replaces a memory file.
 *
 * @throws {ApiError} On any failure
 */
export async function putMemory(file: MemoryFile): Promise<void> {
  const { name, description, content } = file;
  await send(`/memory/${encodeSegment(name)}`, {
    method: "PUT",
    body: JSON.stringify({ description, content }),
    headers: JSON_HEADERS,
  });
}

/** Deletes a memory file. @throws {ApiError} On any failure. */
export async function deleteMemory(name: string): Promise<void> {
  await send(`/memory/${encodeSegment(name)}`, { method: "DELETE" });
}

/** Fetches the connected folders. @throws {ApiError} On any failure. */
export async function getFolders(): Promise<string[]> {
  const body = await sendForJson<{ folders: string[] }>("/folders");
  return body.folders;
}

/** Replaces the connected folders. @throws {ApiError} On any failure. */
export async function putFolders(folders: string[]): Promise<void> {
  await send("/folders", {
    method: "PUT",
    body: JSON.stringify({ folders }),
    headers: JSON_HEADERS,
  });
}

// The folder dialog waits for the person, so it gets a long timeout.
const FOLDER_DIALOG_TIMEOUT_MS = 10 * 60_000;

/**
 * Asks the orchestrator to open the Windows folder dialog on this desktop.
 *
 * @param startFolder - Folder the dialog opens in, if any
 * @returns The chosen folder's absolute path, or null if the person cancelled
 * @throws {ApiError} On any failure
 */
export async function browseForFolder(startFolder?: string): Promise<string | null> {
  const body = await sendForJson<{ folder: string | null }>("/folders/browse", {
    ...postJson({ start_folder: startFolder ?? null }),
    timeoutMs: FOLDER_DIALOG_TIMEOUT_MS,
  });
  return body.folder;
}

/** Fetches the index as a graph of files for the index map. @throws {ApiError} On any failure. */
export function getKnowledgeGraph(): Promise<KnowledgeGraph> {
  return sendForJson<KnowledgeGraph>("/knowledge/graph");
}

/** Fetches indexing progress for every connected folder. @throws {ApiError} On any failure. */
export function getKnowledgeStatus(): Promise<FolderIndexStatus[]> {
  return sendForJson<FolderIndexStatus[]>("/knowledge/status");
}

/** Starts re-indexing every connected folder. @throws {ApiError} On any failure. */
export async function postReindex(): Promise<void> {
  await send("/knowledge/reindex", { method: "POST" });
}

/**
 * Sends recorded audio for local transcription.
 *
 * @param audio - The recording
 * @param contentType - `audio/wav` or `audio/webm`, as the contract requires
 * @returns The transcribed text
 * @throws {ApiError} On any failure
 */
export async function postTranscription(
  audio: Blob,
  contentType: "audio/wav" | "audio/webm"
): Promise<string> {
  const body = await sendForJson<{ text: string }>("/transcriptions", {
    method: "POST",
    body: audio,
    headers: { "Content-Type": contentType },
    timeoutMs: SLOW_REQUEST_TIMEOUT_MS,
  });
  return body.text;
}
