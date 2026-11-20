import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { installMockOrchestrator, MockEventSource, SESSION_ID } from "../test/mock-orchestrator";
import type { SessionAction } from "./session-state";
import { useSessionStream } from "./use-session-stream";

describe("useSessionStream", () => {
  let dispatch: Mock<(action: SessionAction) => void>;
  let onMalformedEvent: Mock<() => void>;
  let pendingFrames: FrameRequestCallback[];

  const runFrames = (): void => {
    const frames = pendingFrames;
    pendingFrames = [];
    act(() => frames.forEach((frame) => frame(0)));
  };

  beforeEach(() => {
    installMockOrchestrator();
    dispatch = vi.fn();
    onMalformedEvent = vi.fn();
    pendingFrames = [];
    vi.stubGlobal("requestAnimationFrame", (frame: FrameRequestCallback) =>
      pendingFrames.push(frame)
    );
    vi.stubGlobal("cancelAnimationFrame", () => {
      pendingFrames = [];
    });
  });

  const renderStream = () =>
    renderHook(() => useSessionStream(SESSION_ID, dispatch, onMalformedEvent));

  it("should subscribe to the session's events URL", () => {
    renderStream();

    expect(MockEventSource.latest().url).toBe(`/api/sessions/${SESSION_ID}/events`);
  });

  it("should batch text deltas into one dispatch per animation frame", () => {
    renderStream();
    const source = MockEventSource.latest();

    act(() => {
      source.emit("text_delta", { text: "One " });
      source.emit("text_delta", { text: "two " });
      source.emit("text_delta", { text: "three" });
    });

    expect(dispatch).not.toHaveBeenCalled();
    expect(pendingFrames).toHaveLength(1);

    runFrames();

    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith({
      type: "stream_event",
      event: { type: "text_delta", payload: { text: "One two three" } },
    });
  });

  it("should flush pending text before a non-text event so order is kept", () => {
    renderStream();
    const source = MockEventSource.latest();

    act(() => {
      source.emit("text_delta", { text: "Answer" });
      source.emit("done", { reason: "answered", model_id: "m:1" });
    });

    const dispatchedTypes = dispatch.mock.calls.map(([action]) =>
      action.type === "stream_event" ? action.event.type : action.type
    );
    expect(dispatchedTypes).toEqual(["text_delta", "done"]);
  });

  it("should treat a server-sent error frame as an event, not a lost connection", () => {
    const { result } = renderStream();
    const source = MockEventSource.latest();

    act(() => {
      source.emitOpen();
      source.emit("error", { error: "E", message: "The turn failed.", trace_id: "t-1" });
    });

    expect(result.current).toBe("open");
    expect(dispatch).toHaveBeenCalledWith({
      type: "stream_event",
      event: {
        type: "error",
        payload: { error: "E", message: "The turn failed.", trace_id: "t-1" },
      },
    });
  });

  it("should report reconnecting when the connection itself fails", () => {
    const { result } = renderStream();

    act(() => MockEventSource.latest().emitConnectionError());

    expect(result.current).toBe("reconnecting");
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("should report a malformed frame instead of dispatching it", () => {
    renderStream();

    act(() => MockEventSource.latest().emitRaw("tool_call", '{"call_id": 7}'));

    expect(onMalformedEvent).toHaveBeenCalledTimes(1);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("should close the stream and drop pending text on unmount", () => {
    const { unmount } = renderStream();
    const source = MockEventSource.latest();
    act(() => source.emit("text_delta", { text: "late" }));

    unmount();
    runFrames();

    expect(source.isClosed).toBe(true);
    expect(dispatch).not.toHaveBeenCalled();
  });
});
