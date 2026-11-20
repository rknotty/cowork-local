import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import {
  emptyResponse,
  errorResponse,
  installMockOrchestrator,
  SESSION_ID,
} from "../../test/mock-orchestrator";
import type { MockOrchestrator } from "../../test/mock-orchestrator";
import { renderInSession } from "../../test/render-helpers";
import type { ApprovalItem } from "../../state/session-state";
import { ApprovalCard } from "./approval-card";

const APPROVAL_ROUTE = `POST /api/sessions/${SESSION_ID}/approvals/req-1`;

const pendingApproval: ApprovalItem = {
  kind: "approval",
  id: "item-1",
  requestId: "req-1",
  callId: "call-1",
  toolName: "write_file",
  tier: 2,
  action: "Overwrite file",
  target: "C:\\Projects\\report.docx",
  decision: null,
};

describe("ApprovalCard", () => {
  let orchestrator: MockOrchestrator;

  beforeEach(() => {
    orchestrator = installMockOrchestrator();
    orchestrator.setRoute(APPROVAL_ROUTE, emptyResponse);
  });

  it("should show the exact action, target, tool and tier", () => {
    renderInSession(<ApprovalCard item={pendingApproval} />);

    expect(screen.getByText("Overwrite file")).toBeInTheDocument();
    expect(screen.getByText("C:\\Projects\\report.docx")).toBeInTheDocument();
    expect(screen.getByText("write_file")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it.each([
    ["Allow once", "allow_once"],
    ["Allow for this session", "allow_session"],
    ["Deny", "deny"],
  ])("should post decision for the %s button as %s", async (buttonName, decision) => {
    const user = userEvent.setup();
    renderInSession(<ApprovalCard item={pendingApproval} />);

    await user.click(screen.getByRole("button", { name: buttonName }));

    await waitFor(() => expect(orchestrator.requestsFor(APPROVAL_ROUTE)).toHaveLength(1));
    expect(orchestrator.requestsFor(APPROVAL_ROUTE)[0]?.body).toBe(JSON.stringify({ decision }));
  });

  it("should show the server's message and trace ID when the post fails", async () => {
    orchestrator.setRoute(APPROVAL_ROUTE, () =>
      errorResponse(409, "APPROVAL_EXPIRED", "That approval request has expired.")
    );
    const user = userEvent.setup();
    renderInSession(<ApprovalCard item={pendingApproval} />);

    await user.click(screen.getByRole("button", { name: "Deny" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That approval request has expired.");
    expect(alert).toHaveTextContent("trace-test-1");
    expect(screen.getByRole("button", { name: "Deny" })).toBeEnabled();
  });

  it("should show the outcome instead of buttons once decided", () => {
    renderInSession(<ApprovalCard item={{ ...pendingApproval, decision: "allow_session" }} />);

    expect(screen.getByText("Allowed for this session")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Allow once" })).not.toBeInTheDocument();
  });
});
