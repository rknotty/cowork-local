import { useCallback, useId, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, KeyboardEvent, ReactElement } from "react";
import { postMessage, postStop } from "../../api/api-client";
import type { FileUpload } from "../../hooks/use-file-upload";
import { useVoiceRecorder } from "../../hooks/use-voice-recorder";
import type { RecorderPhase } from "../../hooks/use-voice-recorder";
import { shortModelName } from "../../lib/format";
import { useAlerts } from "../../state/alerts-context";
import { useSession } from "../../state/session-context";

interface ComposerProps {
  upload: FileUpload;
  /** Model ID serving the orchestrator role, or null when health is unknown. */
  orchestratorModelId: string | null;
}

interface ComposerDraft {
  draft: string;
  /** False from the moment a send starts until the turn's `done` event. */
  canSend: boolean;
  setDraft: (draft: string) => void;
  appendToDraft: (text: string) => void;
  sendDraft: () => Promise<void>;
  stopTurn: () => Promise<void>;
}

const MIC_LABELS: Record<RecorderPhase, string> = {
  idle: "Record voice input",
  recording: "Stop recording",
  transcribing: "Transcribing",
};

function useComposerDraft(): ComposerDraft {
  const { sessionId, state, dispatch } = useSession();
  const { reportError } = useAlerts();
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  // State updates land on the next render, so a second Enter or click in the
  // same tick would still see isSending as false. The ref closes that window.
  const isSendingRef = useRef(false);
  const canSend = !isSending && !state.isTurnActive && draft.trim().length > 0;

  const appendToDraft = useCallback((text: string): void => {
    setDraft((current) => (current.trim().length > 0 ? `${current} ${text}` : text));
  }, []);

  const sendDraft = async (): Promise<void> => {
    const text = draft.trim();
    if (isSendingRef.current || state.isTurnActive || text.length === 0) {
      return;
    }
    isSendingRef.current = true;
    setIsSending(true);
    try {
      await postMessage(sessionId, text);
      // Marks the turn active, which keeps sending disabled until `done`.
      dispatch({ type: "user_message_sent", text });
      setDraft("");
    } catch (thrown) {
      reportError(thrown);
    } finally {
      isSendingRef.current = false;
      setIsSending(false);
    }
  };

  const stopTurn = async (): Promise<void> => {
    try {
      await postStop(sessionId);
    } catch (thrown) {
      reportError(thrown);
    }
  };

  return { draft, canSend, setDraft, appendToDraft, sendDraft, stopTurn };
}

interface AttachButtonProps {
  upload: FileUpload;
}

function AttachButton({ upload }: AttachButtonProps): ReactElement {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFilesChosen = (event: ChangeEvent<HTMLInputElement>): void => {
    const files = Array.from(event.target.files ?? []);
    // Clearing the input lets the same file be chosen again after an edit.
    event.target.value = "";
    void upload.uploadFiles(files);
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="visually-hidden"
        tabIndex={-1}
        aria-hidden="true"
        onChange={handleFilesChosen}
      />
      <button
        type="button"
        className="button"
        disabled={upload.isUploading}
        onClick={() => inputRef.current?.click()}
      >
        {upload.isUploading ? "Uploading" : "Attach file"}
      </button>
    </>
  );
}

interface MicButtonProps {
  onTranscribed: (text: string) => void;
}

function MicButton({ onTranscribed }: MicButtonProps): ReactElement {
  const recorder = useVoiceRecorder(onTranscribed);
  const label = recorder.isSupported
    ? MIC_LABELS[recorder.phase]
    : "Voice input is not available in this browser";

  return (
    <button
      type="button"
      className={recorder.phase === "recording" ? "button button-danger" : "button"}
      aria-pressed={recorder.phase === "recording"}
      disabled={!recorder.isSupported || recorder.phase === "transcribing"}
      title={label}
      onClick={recorder.toggleRecording}
    >
      <span aria-hidden="true">Mic</span>
      <span className="visually-hidden">{label}</span>
    </button>
  );
}

interface ModelIndicatorProps {
  modelId: string | null;
}

function ModelIndicator({ modelId }: ModelIndicatorProps): ReactElement {
  if (modelId === null) {
    return <span className="composer-model muted">Orchestrator model unknown</span>;
  }
  return (
    <span className="composer-model">
      Orchestrator{" "}
      <span className="model-tag" title={modelId}>
        {shortModelName(modelId)}
      </span>
    </span>
  );
}

interface TurnButtonsProps {
  isTurnActive: boolean;
  canSend: boolean;
  onStop: () => void;
}

function TurnButtons({ isTurnActive, canSend, onStop }: TurnButtonsProps): ReactElement {
  return (
    <>
      <button
        type="button"
        className="button button-danger"
        disabled={!isTurnActive}
        onClick={onStop}
      >
        Stop
      </button>
      <button type="submit" className="button button-primary" disabled={!canSend}>
        Send
      </button>
    </>
  );
}

/**
 * The message box and its controls. Voice input and attachments only ever fill
 * the box or the workspace; a message is sent solely by the user's own action.
 */
export function Composer({ upload, orchestratorModelId }: ComposerProps): ReactElement {
  const { state } = useSession();
  const { draft, canSend, setDraft, appendToDraft, sendDraft, stopTurn } = useComposerDraft();
  const textareaId = useId();

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    void sendDraft();
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void sendDraft();
    }
  };

  return (
    <form className="composer" onSubmit={handleSubmit} aria-label="Message composer">
      <label htmlFor={textareaId} className="visually-hidden">
        Message
      </label>
      <textarea
        id={textareaId}
        rows={3}
        value={draft}
        placeholder="Describe the task. Enter sends, Shift+Enter adds a line."
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      {upload.uploadedNames.length > 0 && (
        <p className="composer-uploads" role="status">
          Added to workspace: {upload.uploadedNames.join(", ")}
        </p>
      )}
      <div className="composer-controls">
        <AttachButton upload={upload} />
        <MicButton onTranscribed={appendToDraft} />
        <ModelIndicator modelId={orchestratorModelId} />
        <span className="composer-spacer" />
        <TurnButtons
          isTurnActive={state.isTurnActive}
          canSend={canSend}
          onStop={() => void stopTurn()}
        />
      </div>
    </form>
  );
}
