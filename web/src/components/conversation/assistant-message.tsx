import type { ReactElement } from "react";
import { formatSeconds, shortModelName } from "../../lib/format";
import type { AssistantTextItem } from "../../state/session-state";
import { MarkdownView } from "../common/markdown-view";

interface AssistantMessageProps {
  item: AssistantTextItem;
}

/** One block of assistant text, streamed or stored, with the model that wrote it. */
export function AssistantMessage({ item }: AssistantMessageProps): ReactElement {
  return (
    <article className="message message-assistant" aria-label="Assistant">
      {/* aria-busy holds announcements until the text settles, so a screen
          reader reads the answer once rather than fragment by fragment. */}
      <div aria-live="polite" aria-busy={item.isStreaming}>
        <MarkdownView text={item.text} />
      </div>
      <p className="message-meta">
        {/* Marked at the point of use so AI output is never mistaken for a
            person's words, including in a copied screenshot. */}
        <span className="ai-label">AI-generated</span>
        {item.modelId.length > 0 && (
          <span>
            by{" "}
            <span className="model-tag" title={item.modelId}>
              {shortModelName(item.modelId)}
            </span>
            . Check before relying on it.
          </span>
        )}
        {item.turnDurationMs !== undefined && (
          <span
            className="turn-duration"
            title="Total time from the message being sent to the response being completed"
          >
            Response time {formatSeconds(item.turnDurationMs)}
          </span>
        )}
      </p>
    </article>
  );
}
