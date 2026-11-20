import { Component } from "react";
import type { ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasFailed: boolean;
}

/**
 * Catches rendering errors so a fault in one component shows a recoverable
 * message instead of React unmounting the whole page and leaving it blank.
 *
 * The error itself is not shown: it may contain internal detail. Developers
 * see it in the browser console, where React already reports it. Nothing is
 * sent anywhere, by design.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  public override state: ErrorBoundaryState = { hasFailed: false };

  public static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasFailed: true };
  }

  public override render(): ReactNode {
    if (!this.state.hasFailed) {
      return this.props.children;
    }
    return (
      <main className="fatal-error" role="alert">
        <h1>Something went wrong</h1>
        <p>
          The page hit an unexpected error and stopped. Your sessions and files are safe: they are
          stored by the orchestrator, not the page.
        </p>
        <button type="button" onClick={() => window.location.reload()}>
          Reload the page
        </button>
      </main>
    );
  }
}
