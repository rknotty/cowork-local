import { vi } from "vitest";
import type { Mock } from "vitest";
import type {
  Health,
  MemoryFile,
  Message,
  Session,
  Skill,
  StreamEvent,
  StreamEventType,
  WorkspaceFile,
} from "../api/types";

type PayloadOf<T extends StreamEventType> = Extract<StreamEvent, { type: T }>["payload"];

/**
 * A stand-in for the browser's EventSource that tests drive by hand. It emits
 * the same DOM event classes a real stream does: MessageEvent for server
 * frames and a plain Event for connection failures.
 */
export class MockEventSource extends EventTarget {
  static instances: MockEventSource[] = [];

  readonly url: string;
  isClosed = false;

  constructor(url: string) {
    super();
    this.url = url;
    MockEventSource.instances.push(this);
  }

  static reset(): void {
    MockEventSource.instances = [];
  }

  static latest(): MockEventSource {
    const latest = MockEventSource.instances.at(-1);
    if (latest === undefined) {
      throw new Error("No EventSource has been opened");
    }
    return latest;
  }

  close(): void {
    this.isClosed = true;
  }

  emit<T extends StreamEventType>(type: T, payload: PayloadOf<T>): void {
    this.emitRaw(type, JSON.stringify(payload));
  }

  emitRaw(type: StreamEventType, rawData: string): void {
    this.dispatchEvent(new MessageEvent(type, { data: rawData }));
  }

  emitOpen(): void {
    this.dispatchEvent(new Event("open"));
  }

  emitConnectionError(): void {
    this.dispatchEvent(new Event("error"));
  }
}

export interface RecordedRequest {
  method: string;
  path: string;
  body: BodyInit | null | undefined;
  headers: Record<string, string>;
}

export type RouteHandler = (request: RecordedRequest) => Response;

export interface MockOrchestrator {
  fetchMock: Mock<typeof fetch>;
  requests: RecordedRequest[];
  /** Replaces the handler for one route, keyed as "METHOD /api/path". */
  setRoute: (routeKey: string, handler: RouteHandler) => void;
  /** Returns the recorded requests for one route, oldest first. */
  requestsFor: (routeKey: string) => RecordedRequest[];
}

/** Builds a JSON response as the orchestrator would send it. */
export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Builds an empty 204 response. */
export function emptyResponse(): Response {
  return new Response(null, { status: 204 });
}

/** Builds an error response in the contract's error shape. */
export function errorResponse(status: number, error: string, message: string): Response {
  return jsonResponse({ error, message, trace_id: "trace-test-1" }, status);
}

export const SESSION_ID = "session-1";

export const HEALTH_FIXTURE: Health = {
  is_healthy: true,
  is_offline: true,
  sandbox_state: "ready",
  roles: { orchestrator: "example-model-14b:2", worker: "example-model-4b:1" },
  context_limit_tokens: 32768,
};

export const SESSION_FIXTURE: Session = {
  session_id: SESSION_ID,
  title: "Quarterly summary",
  workspace_path: "C:\\workspaces\\session-1",
  created_at: "2026-01-15T09:30:00Z",
};

export const FILES_FIXTURE: WorkspaceFile[] = [
  {
    relative_path: "report.docx",
    size_bytes: 20480,
    modified_at: "2026-01-15T09:45:00Z",
    is_changed_this_session: true,
    preview_path: "previews/report.pdf",
  },
  {
    relative_path: "source-data.csv",
    size_bytes: 512,
    modified_at: "2026-01-14T08:00:00Z",
    is_changed_this_session: false,
    preview_path: null,
  },
];

export const SKILLS_FIXTURE: Skill[] = [
  { name: "summarise-document", description: "Summarise a document into key points." },
];

export const MEMORY_FIXTURE: MemoryFile[] = [
  { name: "preferences.md", description: "Writing preferences", content: "Use British English." },
];

const sessionRoot = `/api/sessions/${SESSION_ID}`;

const defaultRoutes = (): Map<string, RouteHandler> =>
  new Map<string, RouteHandler>([
    ["GET /api/health", () => jsonResponse(HEALTH_FIXTURE)],
    ["GET /api/sessions", () => jsonResponse([SESSION_FIXTURE])],
    [
      "POST /api/sessions",
      () => jsonResponse({ ...SESSION_FIXTURE, session_id: "session-2" }, 201),
    ],
    [`GET ${sessionRoot}/messages`, () => jsonResponse([] satisfies Message[])],
    [`POST ${sessionRoot}/messages`, () => jsonResponse({ accepted: true }, 202)],
    [`POST ${sessionRoot}/stop`, emptyResponse],
    [`GET ${sessionRoot}/files`, () => jsonResponse(FILES_FIXTURE)],
    ["GET /api/skills", () => jsonResponse(SKILLS_FIXTURE)],
    ["GET /api/memory", () => jsonResponse(MEMORY_FIXTURE)],
    ["GET /api/folders", () => jsonResponse({ folders: ["C:\\Projects"] })],
    ["PUT /api/folders", emptyResponse],
    ["POST /api/transcriptions", () => jsonResponse({ text: "transcribed words" })],
  ]);

const toRecordedRequest = (input: RequestInfo | URL, init?: RequestInit): RecordedRequest => ({
  method: init?.method ?? "GET",
  path: String(input),
  body: init?.body,
  headers: (init?.headers ?? {}) as Record<string, string>,
});

/**
 * Installs a typed in-memory orchestrator: `fetch` is answered from a route
 * table and `EventSource` is replaced by MockEventSource. Unrouted requests get
 * a contract-shaped 404 so a missing route fails loudly rather than hanging.
 * Call from `beforeEach`; globals are restored by Vitest's `unstubGlobals`.
 */
export function installMockOrchestrator(): MockOrchestrator {
  const routes = defaultRoutes();
  const requests: RecordedRequest[] = [];
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const request = toRecordedRequest(input, init);
    requests.push(request);
    const handler = routes.get(`${request.method} ${request.path}`);
    const response =
      handler?.(request) ??
      errorResponse(404, "ROUTE_NOT_MOCKED", "No mock route for this request.");
    return Promise.resolve(response);
  });

  MockEventSource.reset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", MockEventSource);

  return {
    fetchMock,
    requests,
    setRoute: (routeKey, handler) => routes.set(routeKey, handler),
    requestsFor: (routeKey) =>
      requests.filter((request) => `${request.method} ${request.path}` === routeKey),
  };
}
