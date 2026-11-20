import { useId, useState } from "react";
import type { FormEvent, ReactElement } from "react";
import { browseForFolder, getFolders, postReindex, putFolders } from "../../api/api-client";
import type { FolderIndexStatus } from "../../api/types";
import { useApiResource } from "../../hooks/use-api-resource";
import { isAnyIndexing, useIndexingStatus } from "../../hooks/use-indexing-status";
import { announceKnowledgeChanged } from "../../lib/knowledge-events";
import { useAlerts } from "../../state/alerts-context";
import { IndexingStatusLine } from "./indexing-status";

const ABSOLUTE_PATH_PATTERN = /^(?:[A-Za-z]:[\\/]|\\\\|\/)/;

/**
 * Checks a folder path before it is sent, so an obviously unusable entry is
 * caught here rather than by the orchestrator.
 *
 * @param path - The trimmed path the user typed
 * @param existing - Folders already connected
 * @returns A message describing the problem, or null when the path is acceptable
 */
export function validateFolderPath(path: string, existing: string[]): string | null {
  if (!ABSOLUTE_PATH_PATTERN.test(path)) {
    return "Enter an absolute path, for example C:\\Projects\\Reports.";
  }
  if (existing.includes(path)) {
    return "That folder is already connected.";
  }
  return null;
}

interface BrowseButtonProps {
  startFolder: string;
  onChosen: (path: string) => void;
}

/**
 * Opens the Windows folder dialog through the orchestrator. The chosen path
 * fills the field rather than connecting at once: connecting starts indexing,
 * so the person confirms the folder first.
 */
function BrowseButton({ startFolder, onChosen }: BrowseButtonProps): ReactElement {
  const { reportError } = useAlerts();
  const [isWaiting, setIsWaiting] = useState(false);

  const handleClick = (): void => {
    // Stays focusable while waiting (aria-busy) but never opens a second dialog.
    if (isWaiting) {
      return;
    }
    setIsWaiting(true);
    browseForFolder(startFolder.length > 0 ? startFolder : undefined)
      .then((chosen) => {
        if (chosen !== null) {
          onChosen(chosen);
        }
      })
      .catch(reportError)
      .finally(() => setIsWaiting(false));
  };

  return (
    <>
      <button type="button" className="button" aria-busy={isWaiting} onClick={handleClick}>
        {isWaiting ? "Waiting for folder…" : "Browse…"}
      </button>
      {isWaiting && (
        <p className="rail-note" role="status">
          Choose a folder in the window that opened. It may be behind this browser.
        </p>
      )}
    </>
  );
}

interface AddFolderFormProps {
  folders: string[];
  onAdd: (path: string) => Promise<void>;
}

function AddFolderForm({ folders, onAdd }: AddFolderFormProps): ReactElement {
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const inputId = useId();
  const problemId = useId();

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const path = draft.trim();
    const found = validateFolderPath(path, folders);
    setProblem(found);
    if (found === null) {
      void onAdd(path).then(() => setDraft(""));
    }
  };

  return (
    <form className="stacked-form" onSubmit={handleSubmit}>
      <label htmlFor={inputId}>Absolute folder path</label>
      <input
        id={inputId}
        type="text"
        value={draft}
        spellCheck={false}
        aria-invalid={problem !== null}
        aria-describedby={problem !== null ? problemId : undefined}
        onChange={(event) => setDraft(event.target.value)}
      />
      {problem !== null && (
        <p id={problemId} className="field-problem">
          {problem}
        </p>
      )}
      <div className="button-row">
        <BrowseButton
          startFolder={draft.trim()}
          onChosen={(path) => {
            setDraft(path);
            setProblem(null);
          }}
        />
        <button type="submit" className="button button-primary">
          Connect folder
        </button>
      </div>
    </form>
  );
}

interface FolderListProps {
  folders: string[];
  statuses: FolderIndexStatus[];
  onRemove: (folder: string) => void;
}

function FolderList({ folders, statuses, onRemove }: FolderListProps): ReactElement {
  return (
    <ul className="plain-list">
      {folders.map((folder) => (
        <li key={folder} className="folder-item">
          <div className="folder-row">
            <span className="folder-path">{folder}</span>
            <button type="button" className="button button-quiet" onClick={() => onRemove(folder)}>
              Remove<span className="visually-hidden"> {folder}</span>
            </button>
          </div>
          <IndexingStatusLine status={statuses.find((status) => status.folder === folder)} />
        </li>
      ))}
    </ul>
  );
}

/** Lists the folders the agent may work in, their indexing progress, and add or remove. */
export function FoldersEditor(): ReactElement {
  const { resource: folders, reload } = useApiResource(getFolders);
  const { statuses, refresh } = useIndexingStatus();
  const { reportError } = useAlerts();
  const connected = folders ?? [];

  const runAndRefresh = async (action: () => Promise<void>): Promise<void> => {
    try {
      await action();
    } catch (thrown) {
      reportError(thrown);
    } finally {
      // Reload either way so the panel always shows what the orchestrator holds.
      reload();
      refresh();
      announceKnowledgeChanged();
    }
  };
  const saveFolders = (next: string[]): Promise<void> => runAndRefresh(() => putFolders(next));

  return (
    <div className="rail-section-body">
      {connected.length === 0 ? (
        <p className="rail-note">
          {folders === null ? "Loading folders" : "No folders connected."}
        </p>
      ) : (
        <FolderList
          folders={connected}
          statuses={statuses}
          onRemove={(folder) => void saveFolders(connected.filter((known) => known !== folder))}
        />
      )}
      {connected.length > 0 && (
        <button
          type="button"
          className="button button-quiet"
          disabled={isAnyIndexing(statuses)}
          onClick={() => void runAndRefresh(postReindex)}
        >
          Re-index folders
        </button>
      )}
      <AddFolderForm folders={connected} onAdd={(path) => saveFolders([...connected, path])} />
    </div>
  );
}
