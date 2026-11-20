import type { ReactElement } from "react";
import type { FolderIndexStatus } from "../../api/types";

/**
 * Summarises a folder's indexing state in one sentence.
 *
 * @param status - The folder's latest status
 * @returns Plain-English text suitable for the rail and for screen readers
 */
export function describeIndexing(status: FolderIndexStatus): string {
  const processed = status.processed_file_count ?? 0;
  const total = status.total_file_count ?? 0;
  switch (status.state) {
    case "not_indexed":
      return "Not indexed yet.";
    case "scanning":
      return "Finding documents…";
    case "indexing":
      return `Indexing: ${processed} of ${total} files.`;
    case "failed":
      return status.error_message ?? "Indexing stopped.";
    case "done":
      return describeFinishedRun(status);
    default: {
      const exhaustive: never = status.state;
      return exhaustive;
    }
  }
}

function describeFinishedRun(status: FolderIndexStatus): string {
  const searchable = (status.indexed_file_count ?? 0) + (status.unchanged_file_count ?? 0);
  const parts = [`Searchable: ${searchable} of ${status.total_file_count ?? 0} files.`];
  const onlineOnly = status.skipped_online_only_count ?? 0;
  if (onlineOnly > 0) {
    parts.push(`${onlineOnly} online-only, not downloaded.`);
  }
  const failed = status.failed_file_count ?? 0;
  if (failed > 0) {
    parts.push(`${failed} could not be read.`);
  }
  return parts.join(" ");
}

interface IndexingStatusLineProps {
  status: FolderIndexStatus | undefined;
}

/** Shows a folder's indexing progress, outcome and any skipped files. */
export function IndexingStatusLine({ status }: IndexingStatusLineProps): ReactElement | null {
  if (status === undefined) {
    return null;
  }
  const failures = status.failures ?? [];
  return (
    <div className={`indexing-status indexing-${status.state}`}>
      {status.state === "indexing" && (
        <progress
          max={Math.max(status.total_file_count ?? 0, 1)}
          value={status.processed_file_count ?? 0}
          aria-label="Indexing progress"
        />
      )}
      <p className="rail-note" role="status">
        {describeIndexing(status)}
      </p>
      {failures.length > 0 && (
        <details>
          <summary>Files skipped</summary>
          <ul className="plain-list">
            {failures.map((failure) => (
              <li key={failure}>{failure}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
