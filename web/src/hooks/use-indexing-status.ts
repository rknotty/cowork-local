import { useCallback, useEffect, useState } from "react";
import { getKnowledgeStatus } from "../api/api-client";
import type { FolderIndexStatus } from "../api/types";

// Fast while a folder is indexing so progress visibly moves; slow otherwise,
// because idle status rarely changes and each poll is a request.
const ACTIVE_POLL_INTERVAL_MS = 2_000;
const IDLE_POLL_INTERVAL_MS = 15_000;

export interface IndexingStatus {
  /** One entry per connected folder; empty until the first successful poll. */
  statuses: FolderIndexStatus[];
  /** Poll now, for example straight after folders change. */
  refresh: () => void;
}

/**
 * Reports whether any folder is still being scanned or indexed.
 *
 * @param statuses - The latest status list
 * @returns True while at least one folder's run is in progress
 */
export function isAnyIndexing(statuses: FolderIndexStatus[]): boolean {
  return statuses.some((status) => status.state === "scanning" || status.state === "indexing");
}

/**
 * Polls `/api/knowledge/status`. Failures are not raised as alerts: the
 * status bar already reports an unreachable orchestrator, and a repeating
 * alert every two seconds would bury real errors.
 *
 * @returns The latest statuses and a function to poll immediately
 */
export function useIndexingStatus(): IndexingStatus {
  const [statuses, setStatuses] = useState<FolderIndexStatus[]>([]);
  const [pollCount, setPollCount] = useState(0);

  useEffect(() => {
    let isCurrent = true;
    getKnowledgeStatus()
      .then((loaded) => {
        if (isCurrent) {
          setStatuses(loaded);
        }
      })
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, [pollCount]);

  const isActive = isAnyIndexing(statuses);
  useEffect(() => {
    const interval = isActive ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS;
    const timer = window.setTimeout(() => setPollCount((count) => count + 1), interval);
    return () => window.clearTimeout(timer);
  }, [isActive, pollCount]);

  const refresh = useCallback((): void => setPollCount((count) => count + 1), []);
  return { statuses, refresh };
}
