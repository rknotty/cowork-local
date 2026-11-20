import { useEffect } from "react";

// The folder list and the index map are separate components with separate
// polls. A window event lets a folder change refresh the map at once instead
// of waiting up to 30 seconds for its next poll.
const KNOWLEDGE_CHANGED_EVENT = "local-workbench:knowledge-changed";

/** Tells every listener that connected folders or the index have changed. */
export function announceKnowledgeChanged(): void {
  window.dispatchEvent(new Event(KNOWLEDGE_CHANGED_EVENT));
}

/**
 * Calls `onChange` whenever `announceKnowledgeChanged` runs.
 *
 * @param onChange - Must be referentially stable (for example from useCallback)
 */
export function useKnowledgeChanged(onChange: () => void): void {
  useEffect(() => {
    window.addEventListener(KNOWLEDGE_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(KNOWLEDGE_CHANGED_EVENT, onChange);
  }, [onChange]);
}
