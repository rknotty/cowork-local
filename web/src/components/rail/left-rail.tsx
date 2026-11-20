import type { ReactElement, ReactNode } from "react";
import type { Health, Session } from "../../api/types";
import type { ThemeChoice } from "../../hooks/use-theme";
import { FoldersEditor } from "./folders-editor";
import { SessionList } from "./session-list";
import { SettingsPanel } from "./settings-panel";
import { SkillsBrowser } from "./skills-browser";

export type CentreView = "conversation" | "memory";

export interface LeftRailProps {
  sessions: Session[] | null;
  activeSessionId: string | null;
  centreView: CentreView;
  health: Health | null;
  theme: ThemeChoice;
  onSelectSession: (sessionId: string) => void;
  onRenameSession: (sessionId: string, title: string) => void;
  onNewSession: () => void;
  onOpenMemory: () => void;
  onThemeChange: (theme: ThemeChoice) => void;
}

interface RailSectionProps {
  title: string;
  children: ReactNode;
}

function RailSection({ title, children }: RailSectionProps): ReactElement {
  return (
    <details className="rail-section">
      <summary>{title}</summary>
      {children}
    </details>
  );
}

/** The left rail: sessions, connected folders, skills, memory and settings. */
export function LeftRail(props: LeftRailProps): ReactElement {
  const isMemoryOpen = props.centreView === "memory";
  return (
    <nav className="left-rail" aria-label="Sessions and workspace">
      <button type="button" className="button button-primary" onClick={props.onNewSession}>
        New session
      </button>
      <h2 className="rail-heading">Sessions</h2>
      <SessionList
        sessions={props.sessions}
        activeSessionId={isMemoryOpen ? null : props.activeSessionId}
        onSelect={props.onSelectSession}
        onRename={props.onRenameSession}
      />
      <RailSection title="Connected folders">
        <FoldersEditor />
      </RailSection>
      <RailSection title="Skills">
        <SkillsBrowser />
      </RailSection>
      <button
        type="button"
        className="rail-link"
        aria-current={isMemoryOpen ? "page" : undefined}
        onClick={props.onOpenMemory}
      >
        Memory
      </button>
      <RailSection title="Settings">
        <SettingsPanel
          health={props.health}
          theme={props.theme}
          onThemeChange={props.onThemeChange}
        />
      </RailSection>
    </nav>
  );
}
