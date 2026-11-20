import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, ReactElement, RefObject } from "react";
import type { Session } from "../../api/types";
import { formatTimestamp } from "../../lib/format";

const MAX_TITLE_LENGTH = 120;

interface SessionNameEditorProps {
  initialTitle: string;
  onSave: (title: string) => void;
  onClose: () => void;
}

/** Focuses and selects the field once, when editing starts. */
function useSelectOnMount(): RefObject<HTMLInputElement | null> {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);
  return inputRef;
}

/**
 * In-place name field. Enter or leaving the field saves; Escape cancels.
 * A blank or unchanged name saves nothing.
 */
function SessionNameEditor({
  initialTitle,
  onSave,
  onClose,
}: SessionNameEditorProps): ReactElement {
  const [draft, setDraft] = useState(initialTitle);
  const inputRef = useSelectOnMount();
  // Closing removes the field, which can fire a blur; this stops a cancelled
  // edit being saved by that blur.
  const isClosedRef = useRef(false);
  const inputId = useId();

  const finish = (shouldSave: boolean): void => {
    if (isClosedRef.current) {
      return;
    }
    isClosedRef.current = true;
    const title = draft.trim().replace(/\s+/g, " ");
    if (shouldSave && title.length > 0 && title !== initialTitle) {
      onSave(title);
    }
    onClose();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
    }
  };

  return (
    <form
      className="session-rename-form"
      onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        finish(true);
      }}
    >
      <label htmlFor={inputId} className="visually-hidden">
        Session name
      </label>
      <input
        ref={inputRef}
        id={inputId}
        type="text"
        value={draft}
        maxLength={MAX_TITLE_LENGTH}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => finish(true)}
      />
    </form>
  );
}

interface SessionRowProps {
  session: Session;
  isActive: boolean;
  onSelect: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => void;
}

function SessionRow({ session, isActive, onSelect, onRename }: SessionRowProps): ReactElement {
  const [isEditing, setIsEditing] = useState(false);

  if (isEditing) {
    return (
      <li className="session-row">
        <SessionNameEditor
          initialTitle={session.title}
          onSave={(title) => onRename(session.session_id, title)}
          onClose={() => setIsEditing(false)}
        />
      </li>
    );
  }
  return (
    <li className={isActive ? "session-row is-active" : "session-row"}>
      <button
        type="button"
        className="session-button"
        aria-current={isActive ? "page" : undefined}
        onClick={() => onSelect(session.session_id)}
      >
        <span className="session-title">{session.title}</span>
        <span className="session-date">{formatTimestamp(session.created_at)}</span>
      </button>
      <button
        type="button"
        className="session-rename"
        aria-label={`Rename ${session.title}`}
        onClick={() => setIsEditing(true)}
      >
        Rename
      </button>
    </li>
  );
}

interface SessionListProps {
  /** Null while the first load is in flight. */
  sessions: Session[] | null;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => void;
}

/** The session list, newest first as the orchestrator returns it, with in-place renaming. */
export function SessionList({
  sessions,
  activeSessionId,
  onSelect,
  onRename,
}: SessionListProps): ReactElement {
  if (sessions === null) {
    return <p className="rail-note">Loading sessions</p>;
  }
  if (sessions.length === 0) {
    return <p className="rail-note">No sessions yet.</p>;
  }
  return (
    <ul className="session-list">
      {sessions.map((session) => (
        <SessionRow
          key={session.session_id}
          session={session}
          isActive={session.session_id === activeSessionId}
          onSelect={onSelect}
          onRename={onRename}
        />
      ))}
    </ul>
  );
}
