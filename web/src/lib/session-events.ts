import { useEffect } from "react";

// The session list lives outside any one session's event stream. When a turn
// finishes the orchestrator may have named the session, so the stream
// announces it and the list reloads.
const SESSIONS_CHANGED_EVENT = "local-workbench:sessions-changed";

/** Tells the session list that session names or order may have changed. */
export function announceSessionsChanged(): void {
  window.dispatchEvent(new Event(SESSIONS_CHANGED_EVENT));
}

/**
 * Calls `onChange` whenever `announceSessionsChanged` runs.
 *
 * @param onChange - Must be referentially stable (for example from useCallback)
 */
export function useSessionsChanged(onChange: () => void): void {
  useEffect(() => {
    window.addEventListener(SESSIONS_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(SESSIONS_CHANGED_EVENT, onChange);
  }, [onChange]);
}
