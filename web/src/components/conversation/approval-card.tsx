import { useId, useState } from "react";
import type { ReactElement } from "react";
import { postApproval } from "../../api/api-client";
import type { ApprovalDecision } from "../../api/types";
import { useAlerts } from "../../state/alerts-context";
import { useSession } from "../../state/session-context";
import type { ApprovalItem } from "../../state/session-state";

interface ApprovalCardProps {
  item: ApprovalItem;
}

interface DecisionOption {
  decision: ApprovalDecision;
  label: string;
  className: string;
}

const DECISION_OPTIONS: readonly DecisionOption[] = [
  { decision: "allow_once", label: "Allow once", className: "button button-primary" },
  { decision: "allow_session", label: "Allow for this session", className: "button" },
  { decision: "deny", label: "Deny", className: "button button-danger" },
];

const DECISION_OUTCOMES: Record<ApprovalDecision, string> = {
  allow_once: "Allowed once",
  allow_session: "Allowed for this session",
  deny: "Denied",
};

function ApprovalFacts({ item }: ApprovalCardProps): ReactElement {
  return (
    <dl className="fact-list">
      <dt>Action</dt>
      <dd>
        <code className="fact-code">{item.action}</code>
      </dd>
      <dt>Target</dt>
      <dd>
        <code className="fact-code">{item.target}</code>
      </dd>
      <dt>Tool</dt>
      <dd>{item.toolName}</dd>
      <dt>Tier</dt>
      <dd>{item.tier}</dd>
    </dl>
  );
}

/**
 * An inline prompt for an action the agent may not take without the user's
 * say-so. It shows exactly what was requested and posts the chosen decision.
 */
export function ApprovalCard({ item }: ApprovalCardProps): ReactElement {
  const { sessionId, dispatch } = useSession();
  const { reportError } = useAlerts();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const headingId = useId();

  const handleDecision = async (decision: ApprovalDecision): Promise<void> => {
    setIsSubmitting(true);
    try {
      await postApproval(sessionId, item.requestId, decision);
      dispatch({ type: "approval_decided", requestId: item.requestId, decision });
    } catch (thrown) {
      reportError(thrown);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="card prompt-card" aria-labelledby={headingId}>
      <h3 id={headingId} className="card-heading">
        Approval needed
      </h3>
      <ApprovalFacts item={item} />
      {item.decision === null ? (
        <div className="button-row">
          {DECISION_OPTIONS.map((option) => (
            <button
              key={option.decision}
              type="button"
              className={option.className}
              disabled={isSubmitting}
              onClick={() => void handleDecision(option.decision)}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : (
        <p className="card-line" role="status">
          {DECISION_OUTCOMES[item.decision]}
        </p>
      )}
    </section>
  );
}
