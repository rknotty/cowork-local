import { render } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { AlertList } from "../components/common/alert-list";
import { AlertsProvider } from "../state/alerts-context";
import { SessionProvider } from "../state/session-context";
import { SESSION_ID } from "./mock-orchestrator";

/**
 * Renders a component inside the real alert and session providers, with the
 * alert list mounted so tests can assert on reported errors. Requires
 * installMockOrchestrator() to have run first.
 */
export function renderInSession(ui: ReactElement): RenderResult {
  return render(
    <AlertsProvider>
      <SessionProvider sessionId={SESSION_ID}>
        <AlertList />
        {ui}
      </SessionProvider>
    </AlertsProvider>
  );
}
