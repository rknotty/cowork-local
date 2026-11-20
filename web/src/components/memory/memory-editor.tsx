import { useId, useState } from "react";
import type { FormEvent, ReactElement } from "react";
import type { MemoryFile } from "../../api/types";

interface MemoryEditorProps {
  /** The file being edited, or null to create a new one. */
  file: MemoryFile | null;
  onSave: (file: MemoryFile) => Promise<void>;
  onCancel: () => void;
}

const EMPTY_MEMORY_FILE: MemoryFile = { name: "", description: "", content: "" };

/** A form for creating a memory file or editing an existing one's text. */
export function MemoryEditor({ file, onSave, onCancel }: MemoryEditorProps): ReactElement {
  const [draft, setDraft] = useState<MemoryFile>(file ?? EMPTY_MEMORY_FILE);
  const [isSaving, setIsSaving] = useState(false);
  const fieldId = useId();
  const isNewFile = file === null;

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setIsSaving(true);
    void onSave({ ...draft, name: draft.name.trim() }).finally(() => setIsSaving(false));
  };

  return (
    <form className="stacked-form memory-editor" onSubmit={handleSubmit}>
      {isNewFile && (
        <>
          <label htmlFor={`${fieldId}-name`}>File name</label>
          <input
            id={`${fieldId}-name`}
            type="text"
            required
            value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          />
        </>
      )}
      <label htmlFor={`${fieldId}-description`}>Description</label>
      <input
        id={`${fieldId}-description`}
        type="text"
        value={draft.description}
        onChange={(event) => setDraft({ ...draft, description: event.target.value })}
      />
      <label htmlFor={`${fieldId}-content`}>Content</label>
      <textarea
        id={`${fieldId}-content`}
        rows={10}
        value={draft.content}
        onChange={(event) => setDraft({ ...draft, content: event.target.value })}
      />
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={isSaving}>
          Save
        </button>
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
