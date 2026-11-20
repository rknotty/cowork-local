import { useCallback, useEffect, useState } from "react";
import { getKnowledgeGraph } from "../api/api-client";
import type { KnowledgeGraph } from "../api/types";
import { useKnowledgeChanged } from "../lib/knowledge-events";
import { isAnyIndexing, useIndexingStatus } from "./use-indexing-status";

// While a folder indexes, refresh fast enough that dots visibly appear as
// files are processed. Otherwise the graph only changes when folders do.
const BUILDING_POLL_INTERVAL_MS = 2_000;
const IDLE_POLL_INTERVAL_MS = 30_000;

export interface KnowledgeGraphState {
  graph: KnowledgeGraph | null;
  isBuilding: boolean;
}

/**
 * Polls `/api/knowledge/graph`, faster while any folder is indexing. Failures
 * keep the last good graph rather than raising alerts: the status bar already
 * reports an unreachable orchestrator.
 *
 * @returns The latest graph (null until the first load) and whether indexing is running
 */
export function useKnowledgeGraph(): KnowledgeGraphState {
  const { statuses, refresh: refreshStatuses } = useIndexingStatus();
  const isBuilding = isAnyIndexing(statuses);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [pollCount, setPollCount] = useState(0);

  // A folder added or removed changes the map now, not at the next poll.
  const refreshNow = useCallback((): void => {
    setPollCount((count) => count + 1);
    refreshStatuses();
  }, [refreshStatuses]);
  useKnowledgeChanged(refreshNow);

  useEffect(() => {
    let isCurrent = true;
    getKnowledgeGraph()
      .then((loaded) => {
        if (isCurrent) {
          setGraph(loaded);
        }
      })
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, [pollCount]);

  useEffect(() => {
    const interval = isBuilding ? BUILDING_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS;
    const timer = window.setTimeout(() => setPollCount((count) => count + 1), interval);
    return () => window.clearTimeout(timer);
  }, [isBuilding, pollCount]);

  return { graph, isBuilding };
}
