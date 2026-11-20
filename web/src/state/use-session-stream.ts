import { useEffect, useState } from "react";
import type { Dispatch } from "react";
import { buildEventsUrl } from "../api/api-client";
import { parseStreamEvent } from "../api/event-parser";
import { STREAM_EVENT_TYPES } from "../api/types";
import type { StreamEventType } from "../api/types";
import { announceSessionsChanged } from "../lib/session-events";
import { createDeltaBatcher } from "./delta-batcher";
import type { DeltaBatcher } from "./delta-batcher";
import type { SessionAction } from "./session-state";

export type StreamConnection = "connecting" | "open" | "reconnecting";

interface StreamHandlers {
  batcher: DeltaBatcher;
  onMalformedEvent: () => void;
  onConnectionLost: () => void;
}

const buildListener =
  (type: StreamEventType, handlers: StreamHandlers) =>
  (domEvent: Event): void => {
    // The contract's `error` event shares its name with EventSource's own
    // connection-failure event. Only server frames are MessageEvents.
    if (!(domEvent instanceof MessageEvent)) {
      handlers.onConnectionLost();
      return;
    }
    const parsed = typeof domEvent.data === "string" ? parseStreamEvent(type, domEvent.data) : null;
    if (parsed === null) {
      handlers.onMalformedEvent();
      return;
    }
    handlers.batcher.push(parsed);
    if (parsed.type === "done") {
      // The orchestrator names a new session just before a turn ends.
      announceSessionsChanged();
    }
  };

/**
 * Subscribes to a session's server-sent event stream for the lifetime of the
 * component and dispatches each validated event to the session reducer. Text
 * deltas are batched per animation frame. EventSource reconnects by itself.
 *
 * @param sessionId - The session to subscribe to
 * @param dispatch - The session reducer's dispatch
 * @param onMalformedEvent - Called when a frame fails contract validation; must be stable
 * @returns The current connection state, for display only
 */
export function useSessionStream(
  sessionId: string,
  dispatch: Dispatch<SessionAction>,
  onMalformedEvent: () => void
): StreamConnection {
  const [connection, setConnection] = useState<StreamConnection>("connecting");

  useEffect(() => {
    const source = new EventSource(buildEventsUrl(sessionId));
    const batcher = createDeltaBatcher((event) => dispatch({ type: "stream_event", event }));
    const onConnectionLost = (): void => setConnection("reconnecting");
    const handlers: StreamHandlers = { batcher, onMalformedEvent, onConnectionLost };
    const listeners = STREAM_EVENT_TYPES.map((type) => ({
      type,
      listener: buildListener(type, handlers),
    }));
    listeners.forEach(({ type, listener }) => source.addEventListener(type, listener));
    const handleOpen = (): void => setConnection("open");
    source.addEventListener("open", handleOpen);

    return () => {
      listeners.forEach(({ type, listener }) => source.removeEventListener(type, listener));
      source.removeEventListener("open", handleOpen);
      source.close();
      batcher.cancel();
    };
  }, [sessionId, dispatch, onMalformedEvent]);

  return connection;
}
