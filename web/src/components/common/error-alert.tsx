import type { ReactElement } from "react";

interface ErrorAlertProps {
  message: string;
  traceId: string;
  onDismiss: () => void;
}

/** A dismissible inline error showing only the server's safe message and trace ID. */
export function ErrorAlert({ message, traceId, onDismiss }: ErrorAlertProps): ReactElement {
  return (
    <div className="alert" role="alert">
      <div className="alert-body">
        <p className="alert-message">{message}</p>
        {traceId.length > 0 && (
          <p className="alert-trace">
            Trace ID: <code>{traceId}</code>
          </p>
        )}
      </div>
      <button type="button" className="button button-quiet" onClick={onDismiss}>
        Dismiss<span className="visually-hidden"> error: {message}</span>
      </button>
    </div>
  );
}
