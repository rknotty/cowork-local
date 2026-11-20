import { useCallback, useId } from "react";
import type { ReactElement } from "react";
import { buildFileUrl, getFileText } from "../../api/api-client";
import type { ArtefactPayload } from "../../api/types";
import { useApiResource } from "../../hooks/use-api-resource";
import { buildHtmlPreviewDocument, buildSvgPreviewDocument } from "../../lib/artefact-document";
import { useSession } from "../../state/session-context";
import { MarkdownView } from "../common/markdown-view";

interface ArtefactBodyProps {
  sessionId: string;
  artefact: ArtefactPayload;
  revision: number;
}

type SourceKind = "html" | "svg" | "markdown" | "text";

interface SourceViewProps {
  kind: SourceKind;
  source: string;
  title: string;
}

function SourceView({ kind, source, title }: SourceViewProps): ReactElement {
  switch (kind) {
    case "html":
    case "svg": {
      const build = kind === "html" ? buildHtmlPreviewDocument : buildSvgPreviewDocument;
      // allow-scripts without allow-same-origin gives the preview an opaque
      // origin, so it cannot read this app's storage or call the API.
      return (
        <iframe
          className="preview-frame"
          title={`Preview of ${title}`}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          srcDoc={build(source)}
        />
      );
    }
    case "markdown":
      return <MarkdownView text={source} />;
    case "text":
      return <pre className="card-pre preview-text">{source}</pre>;
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

function SourceArtefact({ sessionId, artefact, revision }: ArtefactBodyProps): ReactElement {
  const { relative_path: relativePath, kind } = artefact;
  const load = useCallback(() => getFileText(sessionId, relativePath), [sessionId, relativePath]);
  const { resource: source, isLoading } = useApiResource(load, revision);

  if (source === null) {
    return <p className="empty-state">{isLoading ? "Loading preview" : "No preview loaded."}</p>;
  }
  return <SourceView kind={kind as SourceKind} source={source} title={relativePath} />;
}

function RenderedArtefact({ sessionId, artefact }: ArtefactBodyProps): ReactElement {
  const { relative_path: relativePath, preview_path: previewPath } = artefact;
  if (previewPath === null) {
    return (
      <p className="empty-state">
        No preview render is available for this file. The sandbox that produces renders may be
        unavailable. You can still download the original.
      </p>
    );
  }
  const previewUrl = buildFileUrl(sessionId, previewPath);
  if (previewPath.toLowerCase().endsWith(".png")) {
    return (
      <img className="preview-image" src={previewUrl} alt={`Rendered preview of ${relativePath}`} />
    );
  }
  return <iframe className="preview-frame" title={`Preview of ${relativePath}`} src={previewUrl} />;
}

function ArtefactBody(props: ArtefactBodyProps): ReactElement {
  switch (props.artefact.kind) {
    case "html":
    case "svg":
    case "markdown":
    case "text":
      return <SourceArtefact {...props} />;
    case "docx":
    case "pptx":
    case "xlsx":
    case "pdf":
      return <RenderedArtefact {...props} />;
    default: {
      const exhaustive: never = props.artefact.kind;
      return exhaustive;
    }
  }
}

/** Previews the selected artefact and offers the original file for download. */
export function ArtefactPreview(): ReactElement {
  const { sessionId, state, dispatch } = useSession();
  const pickerId = useId();
  const selected = state.artefacts.find(
    (artefact) => artefact.relative_path === state.selectedArtefactPath
  );
  if (selected === undefined) {
    return (
      <p className="empty-state">Files the agent creates or changes will be previewed here.</p>
    );
  }
  const handlePick = (relativePath: string): void => {
    const artefact = state.artefacts.find((known) => known.relative_path === relativePath);
    if (artefact !== undefined) {
      dispatch({ type: "artefact_opened", artefact });
    }
  };

  return (
    <div className="artefact">
      <div className="artefact-toolbar">
        <label htmlFor={pickerId}>Artefact</label>
        <select
          id={pickerId}
          value={selected.relative_path}
          onChange={(event) => handlePick(event.target.value)}
        >
          {state.artefacts.map((artefact) => (
            <option key={artefact.relative_path} value={artefact.relative_path}>
              {artefact.relative_path}
            </option>
          ))}
        </select>
        <a className="button" href={buildFileUrl(sessionId, selected.relative_path)} download>
          Download<span className="visually-hidden"> {selected.relative_path}</span>
        </a>
      </div>
      <ArtefactBody
        key={selected.relative_path}
        sessionId={sessionId}
        artefact={selected}
        revision={state.workspaceRevision}
      />
    </div>
  );
}
