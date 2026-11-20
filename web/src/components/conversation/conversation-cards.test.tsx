import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { emptyResponse, installMockOrchestrator, SESSION_ID } from "../../test/mock-orchestrator";
import type { MockOrchestrator } from "../../test/mock-orchestrator";
import { renderInSession } from "../../test/render-helpers";
import type { QuestionItem, ToolCallItem } from "../../state/session-state";
import { AssistantMessage } from "./assistant-message";
import { QuestionCard } from "./question-card";
import { ToolCallCard } from "./tool-call-card";

const ANSWER_ROUTE = `POST /api/sessions/${SESSION_ID}/answers/q-1`;

const question: QuestionItem = {
  kind: "question",
  id: "item-1",
  questionId: "q-1",
  question: "Which format should the report use?",
  options: ["PDF", "Word"],
  answer: null,
};

const finishedCall: ToolCallItem = {
  kind: "tool_call",
  id: "item-2",
  callId: "call-1",
  toolName: "read_file",
  arguments: { path: "notes.txt" },
  tier: 1,
  summary: "Read notes.txt",
  status: "ok",
  resultPreview: "first line of notes",
  durationMs: 1500,
};

describe("QuestionCard", () => {
  let orchestrator: MockOrchestrator;

  beforeEach(() => {
    orchestrator = installMockOrchestrator();
    orchestrator.setRoute(ANSWER_ROUTE, emptyResponse);
  });

  it("should post the chosen option as the answer", async () => {
    const user = userEvent.setup();
    renderInSession(<QuestionCard item={question} />);

    await user.click(screen.getByRole("button", { name: "Word" }));

    await waitFor(() => expect(orchestrator.requestsFor(ANSWER_ROUTE)).toHaveLength(1));
    expect(orchestrator.requestsFor(ANSWER_ROUTE)[0]?.body).toBe(
      JSON.stringify({ answer: "Word" })
    );
  });

  it("should post a trimmed free-text answer", async () => {
    const user = userEvent.setup();
    renderInSession(<QuestionCard item={question} />);

    await user.type(screen.getByLabelText("Your own answer"), "  Markdown  ");
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    await waitFor(() => expect(orchestrator.requestsFor(ANSWER_ROUTE)).toHaveLength(1));
    expect(orchestrator.requestsFor(ANSWER_ROUTE)[0]?.body).toBe(
      JSON.stringify({ answer: "Markdown" })
    );
  });

  it("should not allow an empty free-text answer", () => {
    renderInSession(<QuestionCard item={question} />);

    expect(screen.getByRole("button", { name: "Send answer" })).toBeDisabled();
  });

  it("should show the given answer once answered", () => {
    renderInSession(<QuestionCard item={{ ...question, answer: "PDF" }} />);

    expect(screen.getByText("You answered: PDF")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Word" })).not.toBeInTheDocument();
  });
});

describe("ToolCallCard", () => {
  it("should be collapsed by default showing name, summary, status and duration", () => {
    render(<ToolCallCard item={finishedCall} />);

    const toggle = screen.getByRole("button", { name: /read_file/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent("Read notes.txt");
    expect(toggle).toHaveTextContent("Succeeded");
    expect(toggle).toHaveTextContent("1.5 s");
    expect(screen.queryByText("first line of notes")).not.toBeInTheDocument();
  });

  it("should show full arguments and the result preview when expanded", async () => {
    const user = userEvent.setup();
    render(<ToolCallCard item={finishedCall} />);

    await user.click(screen.getByRole("button", { name: /read_file/ }));

    expect(screen.getByRole("button", { name: /read_file/ })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(screen.getByText(/"path": "notes.txt"/)).toBeInTheDocument();
    expect(screen.getByText("first line of notes")).toBeInTheDocument();
  });

  it("should show a running call without a duration", () => {
    render(<ToolCallCard item={{ ...finishedCall, status: "running", durationMs: null }} />);

    expect(screen.getByRole("button", { name: /read_file/ })).toHaveTextContent("Running");
  });
});

describe("AssistantMessage", () => {
  it("should show the short model name with the full ID on hover", () => {
    render(
      <AssistantMessage
        item={{
          kind: "assistant_text",
          id: "item-3",
          text: "The **answer**.",
          modelId: "example-model-14b:2",
          isStreaming: false,
        }}
      />
    );

    expect(screen.getByText("example-model-14b")).toHaveAttribute("title", "example-model-14b:2");
    expect(screen.getByText("answer").tagName).toBe("STRONG");
  });

  it("should mark the streaming region as a polite, busy live region", () => {
    const { container } = render(
      <AssistantMessage
        item={{ kind: "assistant_text", id: "item-4", text: "Par", modelId: "", isStreaming: true }}
      />
    );

    const liveRegion = container.querySelector("[aria-live]");
    expect(liveRegion).toHaveAttribute("aria-live", "polite");
    expect(liveRegion).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText(/Check before relying on it/)).not.toBeInTheDocument();
  });

  it("should show the response time in seconds in the answer's footer", () => {
    render(
      <AssistantMessage
        item={{
          kind: "assistant_text",
          id: "item-6",
          text: "Done",
          modelId: "m:1",
          isStreaming: false,
          turnDurationMs: 12_430,
        }}
      />
    );

    expect(screen.getByText("Response time 12.4 s")).toBeInTheDocument();
  });

  it("should mark assistant output as AI-generated even before the model is known", () => {
    render(
      <AssistantMessage
        item={{
          kind: "assistant_text",
          id: "item-5",
          text: "Draft",
          modelId: "",
          isStreaming: true,
        }}
      />
    );

    expect(screen.getByText("AI-generated")).toBeInTheDocument();
  });

  it("should not load remote images from model output", () => {
    const { container } = render(
      <AssistantMessage
        item={{
          kind: "assistant_text",
          id: "item-5",
          text: "![chart](https://example.invalid/chart.png)",
          modelId: "",
          isStreaming: false,
        }}
      />
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/Image not loaded: chart/)).toBeInTheDocument();
  });
});
