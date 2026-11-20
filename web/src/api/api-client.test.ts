import { beforeEach, describe, expect, it } from "vitest";
import {
  emptyResponse,
  errorResponse,
  installMockOrchestrator,
  SESSION_ID,
} from "../test/mock-orchestrator";
import type { MockOrchestrator } from "../test/mock-orchestrator";
import {
  buildFileUrl,
  encodeFilePath,
  getFolders,
  getHealth,
  listSessions,
  postApproval,
  postMessage,
  postTranscription,
  putFile,
  putMemory,
} from "./api-client";
import { ApiError, asApiError } from "./api-error";

describe("api client", () => {
  let orchestrator: MockOrchestrator;

  beforeEach(() => {
    orchestrator = installMockOrchestrator();
  });

  it("should map a contract error body to an ApiError with message and trace ID", async () => {
    orchestrator.setRoute("GET /api/sessions", () =>
      errorResponse(404, "SESSION_NOT_FOUND", "That session does not exist.")
    );

    const failure = await listSessions().catch((thrown: unknown) => thrown);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({
      code: "SESSION_NOT_FOUND",
      message: "That session does not exist.",
      traceId: "trace-test-1",
      status: 404,
    });
  });

  it("should use a generic message when the error body is not in the contract shape", async () => {
    orchestrator.setRoute(
      "GET /api/health",
      () => new Response("Traceback (most recent call last): boom", { status: 500 })
    );

    const failure = await getHealth().catch((thrown: unknown) => thrown);

    expect(failure).toMatchObject({
      code: "UNEXPECTED_RESPONSE",
      message: "The request could not be completed.",
      traceId: "",
      status: 500,
    });
  });

  it("should hide raw exception text when fetch itself fails", async () => {
    orchestrator.fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch at socket.js:91"));

    const failure = await getHealth().catch((thrown: unknown) => thrown);

    expect(failure).toMatchObject({ code: "ORCHESTRATOR_UNREACHABLE", traceId: "" });
    expect((failure as ApiError).message).not.toContain("socket.js");
    expect((failure as ApiError).cause).toBeInstanceOf(TypeError);
  });

  it("should report a timeout distinctly from an unreachable orchestrator", async () => {
    orchestrator.fetchMock.mockRejectedValueOnce(new DOMException("timed out", "TimeoutError"));

    const failure = await getHealth().catch((thrown: unknown) => thrown);

    expect(failure).toMatchObject({ code: "REQUEST_TIMED_OUT" });
  });

  it("should wrap a non-ApiError value without exposing its text", () => {
    const wrapped = asApiError(new Error("internal detail"));

    expect(wrapped.message).toBe("The request could not be completed.");
    expect(wrapped.cause).toBeInstanceOf(Error);
  });

  it("should post the message text as JSON to the session", async () => {
    await postMessage(SESSION_ID, "Summarise the report");

    const [request] = orchestrator.requestsFor(`POST /api/sessions/${SESSION_ID}/messages`);
    expect(request?.body).toBe(JSON.stringify({ text: "Summarise the report" }));
    expect(request?.headers["Content-Type"]).toBe("application/json");
  });

  it("should post an approval decision to the request's own URL", async () => {
    const routeKey = `POST /api/sessions/${SESSION_ID}/approvals/req%2F1`;
    orchestrator.setRoute(routeKey, emptyResponse);

    await postApproval(SESSION_ID, "req/1", "allow_session");

    expect(orchestrator.requestsFor(routeKey)[0]?.body).toBe(
      JSON.stringify({ decision: "allow_session" })
    );
  });

  it("should unwrap the folders list", async () => {
    await expect(getFolders()).resolves.toEqual(["C:\\Projects"]);
  });

  it("should send memory description and content but keep the name in the URL", async () => {
    orchestrator.setRoute("PUT /api/memory/notes%20one.md", emptyResponse);

    await putMemory({ name: "notes one.md", description: "Notes", content: "Body" });

    const [request] = orchestrator.requestsFor("PUT /api/memory/notes%20one.md");
    expect(request?.body).toBe(JSON.stringify({ description: "Notes", content: "Body" }));
  });

  it("should upload raw file bytes with PUT", async () => {
    const routeKey = `PUT /api/sessions/${SESSION_ID}/files/my%20notes.txt`;
    orchestrator.setRoute(routeKey, emptyResponse);
    const file = new Blob(["hello"]);

    await putFile(SESSION_ID, "my notes.txt", file);

    expect(orchestrator.requestsFor(routeKey)[0]?.body).toBe(file);
  });

  it("should send audio with its content type and return the transcribed text", async () => {
    const audio = new Blob(["audio"]);

    const text = await postTranscription(audio, "audio/webm");

    const [request] = orchestrator.requestsFor("POST /api/transcriptions");
    expect(text).toBe("transcribed words");
    expect(request?.headers["Content-Type"]).toBe("audio/webm");
    expect(request?.body).toBe(audio);
  });

  it("should encode each path segment but keep the separators", () => {
    expect(encodeFilePath("reports\\Q1 draft/final#2.md")).toBe("reports/Q1%20draft/final%232.md");
    expect(buildFileUrl("s 1", "a/b.txt")).toBe("/api/sessions/s%201/files/a/b.txt");
  });
});
