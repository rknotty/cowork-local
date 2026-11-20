import { useCallback } from "react";
import type { ReactElement } from "react";
import { buildFileUrl, listFiles } from "../../api/api-client";
import type { WorkspaceFile } from "../../api/types";
import { useApiResource } from "../../hooks/use-api-resource";
import { formatBytes, formatTimestamp, inferArtefactKind } from "../../lib/format";
import { useSession } from "../../state/session-context";

interface FilesChangedProps {
  /** Called after a file has been opened in the artefact preview. */
  onPreviewOpened: () => void;
}

interface ChangedFileRowProps {
  sessionId: string;
  file: WorkspaceFile;
  onPreview: (file: WorkspaceFile) => void;
}

function ChangedFileRow({ sessionId, file, onPreview }: ChangedFileRowProps): ReactElement {
  return (
    <li className="file-row">
      <span className="file-path">{file.relative_path}</span>
      <span className="file-meta">
        {formatBytes(file.size_bytes)} · {formatTimestamp(file.modified_at)}
      </span>
      <span className="button-row">
        <button type="button" className="button" onClick={() => onPreview(file)}>
          Preview<span className="visually-hidden"> {file.relative_path}</span>
        </button>
        <a className="button" href={buildFileUrl(sessionId, file.relative_path)} download>
          Download<span className="visually-hidden"> {file.relative_path}</span>
        </a>
      </span>
    </li>
  );
}

/** Lists the workspace files the orchestrator marks as changed this session. */
export function FilesChanged({ onPreviewOpened }: FilesChangedProps): ReactElement {
  const { sessionId, state, dispatch } = useSession();
  const load = useCallback(() => listFiles(sessionId), [sessionId]);
  const { resource: files, isLoading } = useApiResource(load, state.workspaceRevision);
  const changedFiles = (files ?? []).filter((file) => file.is_changed_this_session);

  const handlePreview = (file: WorkspaceFile): void => {
    dispatch({
      type: "artefact_opened",
      artefact: {
        relative_path: file.relative_path,
        kind: inferArtefactKind(file.relative_path),
        preview_path: file.preview_path,
      },
    });
    onPreviewOpened();
  };

  if (files === null) {
    return (
      <p className="empty-state">{isLoading ? "Loading files" : "Files could not be loaded."}</p>
    );
  }
  if (changedFiles.length === 0) {
    return <p className="empty-state">No files have changed in this session.</p>;
  }
  return (
    <ul className="file-list">
      {changedFiles.map((file) => (
        <ChangedFileRow
          key={file.relative_path}
          sessionId={sessionId}
          file={file}
          onPreview={handlePreview}
        />
      ))}
    </ul>
  );
}
