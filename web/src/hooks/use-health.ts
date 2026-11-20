import { useEffect, useState } from "react";
import { getHealth } from "../api/api-client";
import type { Health } from "../api/types";

const HEALTH_POLL_INTERVAL_MS = 15_000;

export interface HealthStatus {
  /** Null until the first successful check, and again whenever a check fails. */
  health: Health | null;
  hasChecked: boolean;
}

/**
 * Polls `/api/health`. A failed check clears the last result instead of raising
 * an alert, because the status bar already shows the orchestrator as unreachable
 * and a repeating alert every poll would bury real errors.
 *
 * @returns The latest health result and whether any check has completed
 */
export function useHealth(): HealthStatus {
  const [status, setStatus] = useState<HealthStatus>({ health: null, hasChecked: false });

  useEffect(() => {
    let isCurrent = true;
    const check = (): void => {
      getHealth()
        .then((health) => {
          if (isCurrent) {
            setStatus({ health, hasChecked: true });
          }
        })
        .catch(() => {
          if (isCurrent) {
            setStatus({ health: null, hasChecked: true });
          }
        });
    };
    check();
    const timer = window.setInterval(check, HEALTH_POLL_INTERVAL_MS);
    return () => {
      isCurrent = false;
      window.clearInterval(timer);
    };
  }, []);

  return status;
}
