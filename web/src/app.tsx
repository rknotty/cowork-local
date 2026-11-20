import { useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { AlertList } from "./components/common/alert-list";
import { AppHeader } from "./components/common/app-header";
import { Conversation } from "./components/conversation/conversation";
import { MemoryPage } from "./components/memory/memory-page";
import { RightPanel } from "./components/panel/right-panel";
import { LeftRail } from "./components/rail/left-rail";
import type { CentreView } from "./components/rail/left-rail";
import { StatusBar } from "./components/status/status-bar";
import { useHealth } from "./hooks/use-health";
import { useSessions } from "./hooks/use-sessions";
import { useTheme } from "./hooks/use-theme";
import { AlertsProvider } from "./state/alerts-context";
import { SessionProvider } from "./state/session-context";

interface SessionScopeProps {
  sessionId: string | null;
  children: ReactNode;
}

function SessionScope({ sessionId, children }: SessionScopeProps): ReactElement {
  if (sessionId === null) {
    return <>{children}</>;
  }
  // The key gives each session a fresh reducer and its own event stream.
  return (
    <SessionProvider key={sessionId} sessionId={sessionId}>
      {children}
    </SessionProvider>
  );
}

interface CentreProps {
  view: CentreView;
  hasSession: boolean;
  orchestratorModelId: string | null;
}

function Centre({ view, hasSession, orchestratorModelId }: CentreProps): ReactElement {
  if (view === "memory") {
    return <MemoryPage />;
  }
  if (!hasSession) {
    return <p className="empty-state">Choose a session from the left, or start a new one.</p>;
  }
  return <Conversation orchestratorModelId={orchestratorModelId} />;
}

function Workbench(): ReactElement {
  const healthStatus = useHealth();
  const [theme, setTheme] = useTheme();
  const { sessions, activeSessionId, selectSession, startNewSession, renameSession } =
    useSessions();
  const [centreView, setCentreView] = useState<CentreView>("conversation");
  const orchestratorModelId = healthStatus.health?.roles.orchestrator ?? null;

  const handleSelectSession = (sessionId: string): void => {
    selectSession(sessionId);
    setCentreView("conversation");
  };
  const handleNewSession = (): void => {
    setCentreView("conversation");
    void startNewSession();
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <AppHeader />
      <LeftRail
        sessions={sessions}
        activeSessionId={activeSessionId}
        centreView={centreView}
        health={healthStatus.health}
        theme={theme}
        onSelectSession={handleSelectSession}
        onRenameSession={(sessionId, title) => void renameSession(sessionId, title)}
        onNewSession={handleNewSession}
        onOpenMemory={() => setCentreView("memory")}
        onThemeChange={setTheme}
      />
      <SessionScope sessionId={activeSessionId}>
        <main id="main-content" className="centre" tabIndex={-1}>
          <AlertList />
          <Centre
            view={centreView}
            hasSession={activeSessionId !== null}
            orchestratorModelId={orchestratorModelId}
          />
        </main>
        <RightPanel />
        <StatusBar healthStatus={healthStatus} />
      </SessionScope>
    </div>
  );
}

/** The application root: shared alert state around the three-column workbench. */
export function App(): ReactElement {
  return (
    <AlertsProvider>
      <Workbench />
    </AlertsProvider>
  );
}
