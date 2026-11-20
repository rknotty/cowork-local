import { useCallback, useState } from "react";
import {
  createSession,
  listSessions,
  renameSession as renameSessionRequest,
} from "../api/api-client";
import type { Session } from "../api/types";
import { useSessionsChanged } from "../lib/session-events";
import { useAlerts } from "../state/alerts-context";
import { useApiResource } from "./use-api-resource";

export interface SessionsApi {
  /** Null while the first load is in flight. */
  sessions: Session[] | null;
  /** The chosen session, falling back to the newest; null when there are none. */
  activeSessionId: string | null;
  selectSession: (sessionId: string) => void;
  startNewSession: () => Promise<void>;
  renameSession: (sessionId: string, title: string) => Promise<void>;
}

/**
 * Loads the session list and tracks which session is open. Until the user
 * picks one, the newest session is shown.
 *
 * @returns The sessions, the active session ID and the actions that change them
 */
export function useSessions(): SessionsApi {
  const { resource: sessions, reload } = useApiResource(listSessions);
  const { reportError } = useAlerts();
  const [chosenSessionId, setChosenSessionId] = useState<string | null>(null);

  const startNewSession = useCallback(async (): Promise<void> => {
    try {
      const created = await createSession();
      setChosenSessionId(created.session_id);
      reload();
    } catch (thrown) {
      reportError(thrown);
    }
  }, [reload, reportError]);

  const renameSession = useCallback(
    async (sessionId: string, title: string): Promise<void> => {
      try {
        await renameSessionRequest(sessionId, title);
      } catch (thrown) {
        reportError(thrown);
      } finally {
        // Reload either way, so the list shows the name the orchestrator holds.
        reload();
      }
    },
    [reload, reportError]
  );

  useSessionsChanged(reload);

  const activeSessionId = chosenSessionId ?? sessions?.[0]?.session_id ?? null;
  return {
    sessions,
    activeSessionId,
    selectSession: setChosenSessionId,
    startNewSession,
    renameSession,
  };
}
