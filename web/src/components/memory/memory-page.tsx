import { useState } from "react";
import type { ReactElement } from "react";
import { deleteMemory, listMemory, putMemory } from "../../api/api-client";
import type { MemoryFile } from "../../api/types";
import { useApiResource } from "../../hooks/use-api-resource";
import { useAlerts } from "../../state/alerts-context";
import { MemoryEditor } from "./memory-editor";

// Marks the "new file" editor as open. A NUL character cannot appear in a real
// file name, so this can never collide with an existing memory file.
const NEW_FILE_KEY = "\u0000new";

interface MemoryEntryProps {
  file: MemoryFile;
  isEditing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (file: MemoryFile) => Promise<void>;
  onDelete: () => void;
}

function MemoryEntry(props: MemoryEntryProps): ReactElement {
  const { file, isEditing, onEdit, onCancel, onSave, onDelete } = props;
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);

  return (
    <li className="card memory-entry">
      <h3 className="card-heading">{file.name}</h3>
      {isEditing ? (
        <MemoryEditor file={file} onSave={onSave} onCancel={onCancel} />
      ) : (
        <>
          <p className="card-line muted">{file.description}</p>
          <pre className="card-pre">{file.content}</pre>
          <div className="button-row">
            <button type="button" className="button" onClick={onEdit}>
              Edit<span className="visually-hidden"> {file.name}</span>
            </button>
            {isConfirmingDelete ? (
              <>
                <button type="button" className="button button-danger" onClick={onDelete}>
                  Confirm delete<span className="visually-hidden"> of {file.name}</span>
                </button>
                <button
                  type="button"
                  className="button"
                  onClick={() => setIsConfirmingDelete(false)}
                >
                  Keep
                </button>
              </>
            ) : (
              <button type="button" className="button" onClick={() => setIsConfirmingDelete(true)}>
                Delete<span className="visually-hidden"> {file.name}</span>
              </button>
            )}
          </div>
        </>
      )}
    </li>
  );
}

interface MemoryActions {
  editingKey: string | null;
  setEditingKey: (key: string | null) => void;
  saveFile: (file: MemoryFile) => Promise<void>;
  removeFile: (name: string) => Promise<void>;
}

function useMemoryActions(reload: () => void): MemoryActions {
  const { reportError } = useAlerts();
  const [editingKey, setEditingKey] = useState<string | null>(null);

  const saveFile = async (file: MemoryFile): Promise<void> => {
    try {
      await putMemory(file);
      setEditingKey(null);
      reload();
    } catch (thrown) {
      reportError(thrown);
    }
  };
  const removeFile = async (name: string): Promise<void> => {
    try {
      await deleteMemory(name);
    } catch (thrown) {
      reportError(thrown);
    } finally {
      reload();
    }
  };
  return { editingKey, setEditingKey, saveFile, removeFile };
}

/** The memory page: every memory file, with create, edit and delete. */
export function MemoryPage(): ReactElement {
  const { resource: files, reload } = useApiResource(listMemory);
  const { editingKey, setEditingKey, saveFile, removeFile } = useMemoryActions(reload);
  const closeEditor = (): void => setEditingKey(null);

  return (
    <section className="page" aria-labelledby="memory-heading">
      <header className="page-header">
        <h2 id="memory-heading">Memory</h2>
        <button type="button" className="button" onClick={() => setEditingKey(NEW_FILE_KEY)}>
          New memory file
        </button>
      </header>
      <p className="muted">Notes the agent keeps between sessions. Stored on this machine only.</p>
      {editingKey === NEW_FILE_KEY && (
        <div className="card">
          <MemoryEditor file={null} onSave={saveFile} onCancel={closeEditor} />
        </div>
      )}
      {files === null && <p className="empty-state">Loading memory</p>}
      {files?.length === 0 && <p className="empty-state">No memory files yet.</p>}
      <ul className="plain-list">
        {(files ?? []).map((file) => (
          <MemoryEntry
            key={file.name}
            file={file}
            isEditing={editingKey === file.name}
            onEdit={() => setEditingKey(file.name)}
            onCancel={closeEditor}
            onSave={saveFile}
            onDelete={() => void removeFile(file.name)}
          />
        ))}
      </ul>
    </section>
  );
}
