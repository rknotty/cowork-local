import type { ReactElement } from "react";
import { useSession } from "../../state/session-context";
import type { TimelineItem, TurnNoticeItem } from "../../state/session-state";
import { ErrorAlert } from "../common/error-alert";
import { ApprovalCard } from "./approval-card";
import { AssistantMessage } from "./assistant-message";
import { QuestionCard } from "./question-card";
import { ToolCallCard } from "./tool-call-card";

const NOTICE_TEXT: Record<TurnNoticeItem["reason"], string> = {
  step_limit: "The agent stopped because it reached its step limit.",
  cancelled: "The turn was stopped.",
};

interface TimelineEntryProps {
  item: TimelineItem;
  onDismiss: (itemId: string) => void;
}

function TimelineEntry({ item, onDismiss }: TimelineEntryProps): ReactElement {
  switch (item.kind) {
    case "user_message":
      return (
        <article className="message message-user" aria-label="You">
          <p className="message-user-text">{item.text}</p>
        </article>
      );
    case "assistant_text":
      return <AssistantMessage item={item} />;
    case "tool_call":
      return <ToolCallCard item={item} />;
    case "approval":
      return <ApprovalCard item={item} />;
    case "question":
      return <QuestionCard item={item} />;
    case "turn_error":
      return (
        <ErrorAlert
          message={item.message}
          traceId={item.traceId}
          onDismiss={() => onDismiss(item.id)}
        />
      );
    case "turn_notice":
      return (
        <p className="turn-notice" role="status">
          {NOTICE_TEXT[item.reason]}
        </p>
      );
    default: {
      const exhaustive: never = item;
      return exhaustive;
    }
  }
}

/** The ordered conversation: messages, tool calls, prompts and turn outcomes. */
export function Timeline(): ReactElement {
  const { state, dispatch } = useSession();
  const handleDismiss = (itemId: string): void => dispatch({ type: "item_dismissed", itemId });

  if (state.items.length === 0) {
    return <p className="empty-state">No messages yet. Describe the task below to begin.</p>;
  }
  return (
    <div className="timeline">
      {state.items.map((item) => (
        <TimelineEntry key={item.id} item={item} onDismiss={handleDismiss} />
      ))}
      {state.isTurnActive && (
        <p className="working-indicator" role="status">
          Working
        </p>
      )}
    </div>
  );
}
