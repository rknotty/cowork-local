import { useState } from "react";
import type { ReactElement } from "react";
import { useOptionalSession } from "../../state/session-context";
import { Tabs } from "../common/tabs";
import type { TabDefinition } from "../common/tabs";
import { ArtefactPreview } from "./artefact-preview";
import { FilesChanged } from "./files-changed";
import { IndexMap } from "./index-map";
import { TaskList } from "./task-list";

type PanelTabId = "tasks" | "artefact" | "files";

const PANEL_TABS: readonly TabDefinition<PanelTabId>[] = [
  { id: "tasks", label: "Task list" },
  { id: "artefact", label: "Artefact preview" },
  { id: "files", label: "Files changed" },
];

interface PanelContentProps {
  tabId: PanelTabId;
  onPreviewOpened: () => void;
}

function PanelContent({ tabId, onPreviewOpened }: PanelContentProps): ReactElement {
  switch (tabId) {
    case "tasks":
      return <TaskList />;
    case "artefact":
      return <ArtefactPreview />;
    case "files":
      return <FilesChanged onPreviewOpened={onPreviewOpened} />;
    default: {
      const exhaustive: never = tabId;
      return exhaustive;
    }
  }
}

/**
 * The right-hand panel, split in two: session detail (tasks, artefact
 * preview, changed files) above, the live knowledge index map below.
 */
export function RightPanel(): ReactElement {
  const session = useOptionalSession();
  const [activeTabId, setActiveTabId] = useState<PanelTabId>("tasks");

  return (
    <aside className="right-panel" aria-label="Session detail">
      <div className="right-panel-half">
        {session === null ? (
          <p className="empty-state">Open a session to see its tasks, artefacts and files.</p>
        ) : (
          <Tabs
            idPrefix="session-detail"
            label="Session detail"
            tabs={PANEL_TABS}
            activeTabId={activeTabId}
            onSelect={setActiveTabId}
          >
            <PanelContent tabId={activeTabId} onPreviewOpened={() => setActiveTabId("artefact")} />
          </Tabs>
        )}
      </div>
      <div className="right-panel-half">
        <IndexMap />
      </div>
    </aside>
  );
}
