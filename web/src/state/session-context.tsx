import { createContext, useCallback, useContext, useEffect, useMemo, useReducer } from "react";
import type { Dispatch, ReactElement, ReactNode } from "react";
import { listMessages } from "../api/api-client";
import { ApiError } from "../api/api-error";
import { useAlerts } from "./alerts-context";
import { sessionReducer } from "./session-reducer";
import { INITIAL_SESSION_STATE } from "./session-state";
import type { SessionAction, SessionState } from "./session-state";
import { useSessionStream } from "./use-session-stream";
import type { StreamConnection } from "./use-session-stream";

export interface SessionApi {
  sessionId: string;
  state: SessionState;
  dispatch: Dispatch<SessionAction>;
  connection: StreamConnection;
}

const SessionContext = createContext<SessionApi | null>(null);

interface SessionProviderProps {
  sessionId: string;
  children: ReactNode;
}

/**
 * Owns one session's state: loads its history, subscribes to its event stream
 * and exposes both through context. Mount it with `key={sessionId}` so that
 * switching session starts from a clean state.
 */
export function SessionProvider({ sessionId, children }: SessionProviderProps): ReactElement {
  const [state, dispatch] = useReducer(sessionReducer, INITIAL_SESSION_STATE);
  const { reportError } = useAlerts();

  const handleMalformedEvent = useCallback((): void => {
    reportError(
      new ApiError(
        "MALFORMED_EVENT",
        "The orchestrator sent an event that could not be read.",
        "",
        0
      )
    );
  }, [reportError]);
  const connection = useSessionStream(sessionId, dispatch, handleMalformedEvent);

  useEffect(() => {
    let isCurrent = true;
    listMessages(sessionId)
      .then((messages) => {
        if (isCurrent) {
          dispatch({ type: "history_loaded", messages });
        }
      })
      .catch(reportError);
    return () => {
      isCurrent = false;
    };
  }, [sessionId, reportError]);

  const api = useMemo(
    () => ({ sessionId, state, dispatch, connection }),
    [sessionId, state, connection]
  );
  return <SessionContext.Provider value={api}>{children}</SessionContext.Provider>;
}

/**
 * Accesses the active session's state and dispatch.
 *
 * @returns The session API
 * @throws {Error} If called outside a SessionProvider
 */
export function useSession(): SessionApi {
  const api = useContext(SessionContext);
  if (api === null) {
    throw new Error("useSession must be used inside a SessionProvider");
  }
  return api;
}

/**
 * Like useSession, for parts of the layout that also render with no session.
 *
 * @returns The session API, or null when no session is active
 */
export function useOptionalSession(): SessionApi | null {
  return useContext(SessionContext);
}
