import { useId, useState } from "react";
import type { ReactElement } from "react";
import { formatDuration } from "../../lib/format";
import type { ToolCallItem, ToolCallStatus } from "../../state/session-state";

interface ToolCallCardProps {
  item: ToolCallItem;
}

const STATUS_LABELS: Record<ToolCallStatus, string> = {
  running: "Running",
  ok: "Succeeded",
  error: "Failed",
  denied: "Denied",
  recorded: "Recorded",
};

function ToolCallDetail({ item }: ToolCallCardProps): ReactElement {
  return (
    <>
      {item.tier !== null && <p className="card-line">Permission tier {item.tier}</p>}
      <h4 className="card-subheading">Arguments</h4>
      <pre className="card-pre">{JSON.stringify(item.arguments, null, 2)}</pre>
      <h4 className="card-subheading">Result preview</h4>
      {item.resultPreview.length > 0 ? (
        <pre className="card-pre">{item.resultPreview}</pre>
      ) : (
        <p className="card-line muted">No result yet.</p>
      )}
    </>
  );
}

/**
 * A tool call, collapsed to one line by default. Expanding shows the full
 * arguments and the result preview.
 */
export function ToolCallCard({ item }: ToolCallCardProps): ReactElement {
  const [isExpanded, setIsExpanded] = useState(false);
  const detailId = useId();

  return (
    <section className="card tool-card" aria-label={`Tool call: ${item.toolName}`}>
      <button
        type="button"
        className="tool-card-toggle"
        aria-expanded={isExpanded}
        aria-controls={detailId}
        onClick={() => setIsExpanded((current) => !current)}
      >
        <span className="tool-card-chevron" aria-hidden="true">
          {isExpanded ? "▾" : "▸"}
        </span>
        <span className="tool-card-name">{item.toolName}</span>
        <span className="tool-card-summary">{item.summary}</span>
        <span className={`badge badge-${item.status}`}>{STATUS_LABELS[item.status]}</span>
        {item.durationMs !== null && (
          <span className="tool-card-duration">{formatDuration(item.durationMs)}</span>
        )}
      </button>
      <div id={detailId} className="tool-card-detail" hidden={!isExpanded}>
        {isExpanded && <ToolCallDetail item={item} />}
      </div>
    </section>
  );
}
