import type { ReactElement } from "react";
import { useAlerts } from "../../state/alerts-context";
import { ErrorAlert } from "./error-alert";

/** Renders every outstanding API failure as a dismissible alert. */
export function AlertList(): ReactElement | null {
  const { alerts, dismissAlert } = useAlerts();
  if (alerts.length === 0) {
    return null;
  }
  return (
    <div className="alert-list">
      {alerts.map((alert) => (
        <ErrorAlert
          key={alert.id}
          message={alert.message}
          traceId={alert.traceId}
          onDismiss={() => dismissAlert(alert.id)}
        />
      ))}
    </div>
  );
}
