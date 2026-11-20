import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { asApiError } from "../api/api-error";

export interface AlertEntry {
  id: number;
  message: string;
  traceId: string;
}

export interface AlertsApi {
  alerts: AlertEntry[];
  /** Records a failure for display. Accepts any thrown value; only safe text is kept. */
  reportError: (thrown: unknown) => void;
  dismissAlert: (id: number) => void;
}

const AlertsContext = createContext<AlertsApi | null>(null);

interface AlertsProviderProps {
  children: ReactNode;
}

/** Holds the dismissible error alerts shown above the conversation. */
export function AlertsProvider({ children }: AlertsProviderProps): ReactElement {
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const nextId = useRef(1);

  const reportError = useCallback((thrown: unknown): void => {
    const { message, traceId } = asApiError(thrown);
    const id = nextId.current;
    nextId.current += 1;
    setAlerts((current) => [...current, { id, message, traceId }]);
  }, []);

  const dismissAlert = useCallback((id: number): void => {
    setAlerts((current) => current.filter((alert) => alert.id !== id));
  }, []);

  const api = useMemo(
    () => ({ alerts, reportError, dismissAlert }),
    [alerts, reportError, dismissAlert]
  );
  return <AlertsContext.Provider value={api}>{children}</AlertsContext.Provider>;
}

/**
 * Accesses the alert list and the functions that change it.
 *
 * @returns The alerts API
 * @throws {Error} If called outside an AlertsProvider
 */
export function useAlerts(): AlertsApi {
  const api = useContext(AlertsContext);
  if (api === null) {
    throw new Error("useAlerts must be used inside an AlertsProvider");
  }
  return api;
}
