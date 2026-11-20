import { useCallback, useEffect, useState } from "react";
import { useAlerts } from "../state/alerts-context";

export interface ApiResource<T> {
  /** Null until the first successful load. */
  resource: T | null;
  isLoading: boolean;
  reload: () => void;
}

/**
 * Loads a resource from the API, reloads it on demand or when `revision`
 * changes, and reports failures to the shared alert list.
 *
 * @param load - The API call; must be referentially stable (module function or useCallback)
 * @param revision - Change this number to force a reload
 * @returns The resource, a loading flag and a reload function
 */
export function useApiResource<T>(load: () => Promise<T>, revision = 0): ApiResource<T> {
  const { reportError } = useAlerts();
  const [resource, setResource] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [reloadCount, setReloadCount] = useState(0);

  useEffect(() => {
    let isCurrent = true;
    setIsLoading(true);
    load()
      .then((loaded) => {
        if (isCurrent) {
          setResource(loaded);
        }
      })
      .catch((thrown: unknown) => {
        if (isCurrent) {
          reportError(thrown);
        }
      })
      .finally(() => {
        if (isCurrent) {
          setIsLoading(false);
        }
      });
    return () => {
      isCurrent = false;
    };
  }, [load, revision, reloadCount, reportError]);

  const reload = useCallback((): void => setReloadCount((count) => count + 1), []);
  return { resource, isLoading, reload };
}
