import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./app";
import { PRODUCT_NAME } from "./brand";
import {
  emptyResponse,
  errorResponse,
  installMockOrchestrator,
  jsonResponse,
  MockEventSource,
  SESSION_ID,
} from "./test/mock-orchestrator";
import type { MockOrchestrator } from "./test/mock-orchestrator";

const MESSAGES_ROUTE = `POST /api/sessions/${SESSION_ID}/messages`;

const renderLoadedApp = async (): Promise<void> => {
  render(<App />);
  await screen.findByRole("button", { name: /^Quarterly summary/ });
  await screen.findByLabelText("Message");
};

describe("App", () => {
  let orchestrator: MockOrchestrator;

  beforeEach(() => {
    orchestrator = installMockOrchestrator();
    window.localStorage.clear();
  });

  it("should lay out the product name and the four landmarks", async () => {
    await renderLoadedApp();

    expect(screen.getByText(PRODUCT_NAME)).toBeInTheDocument();
    expect(screen.getByRole("banner")).toContainElement(screen.getByAltText("SCC"));
    expect(screen.getByRole("navigation", { name: "Sessions and workspace" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Session detail" })).toBeInTheDocument();
    expect(screen.getByRole("contentinfo", { name: "Status" })).toBeInTheDocument();
    expect(await screen.findByText("Local only")).toBeInTheDocument();
  });

  it("should send a message and render the streamed answer with its model", async () => {
    const user = userEvent.setup();
    await renderLoadedApp();

    await user.type(screen.getByLabelText("Message"), "Summarise the report{Enter}");
    await waitFor(() => expect(orchestrator.requestsFor(MESSAGES_ROUTE)).toHaveLength(1));
    const source = MockEventSource.latest();
    act(() => {
      source.emit("text_delta", { text: "The report " });
      source.emit("text_delta", { text: "is ready." });
      source.emit("done", { reason: "answered", model_id: "example-model-14b:2" });
    });

    expect(orchestrator.requestsFor(MESSAGES_ROUTE)[0]?.body).toBe(
      JSON.stringify({ text: "Summarise the report" })
    );
    expect(screen.getByText("Summarise the report")).toBeInTheDocument();
    expect(await screen.findByText("The report is ready.")).toBeInTheDocument();
    expect(screen.getByText("AI-generated")).toBeInTheDocument();
    const attribution = screen.getByText(/Check before relying on it/);
    expect(within(attribution).getByText("example-model-14b")).toHaveAttribute(
      "title",
      "example-model-14b:2"
    );
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("should enable Stop only during a turn and post the stop request", async () => {
    const user = userEvent.setup();
    await renderLoadedApp();
    const stopButton = screen.getByRole("button", { name: "Stop" });
    expect(stopButton).toBeDisabled();

    act(() =>
      MockEventSource.latest().emit("tool_call", {
        call_id: "call-1",
        tool_name: "read_file",
        arguments: {},
        tier: 0,
        summary: "Read a file",
      })
    );
    await user.click(stopButton);

    await waitFor(() =>
      expect(orchestrator.requestsFor(`POST /api/sessions/${SESSION_ID}/stop`)).toHaveLength(1)
    );
  });

  it("should show the task list from task_update and replace it on the next one", async () => {
    await renderLoadedApp();
    const source = MockEventSource.latest();

    act(() =>
      source.emit("task_update", { tasks: [{ id: 1, title: "Read input", status: "in_progress" }] })
    );
    expect(screen.getByText("Read input")).toBeInTheDocument();

    act(() =>
      source.emit("task_update", { tasks: [{ id: 2, title: "Write draft", status: "done" }] })
    );

    expect(screen.queryByText("Read input")).not.toBeInTheDocument();
    expect(screen.getByText("Write draft")).toBeInTheDocument();
  });

  it("should list only files changed this session and open one in the preview tab", async () => {
    const user = userEvent.setup();
    await renderLoadedApp();

    await user.click(screen.getByRole("tab", { name: "Files changed" }));

    expect(await screen.findByText("report.docx", { selector: ".file-path" })).toBeInTheDocument();
    expect(screen.queryByText("source-data.csv")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Preview report.docx/ }));

    expect(screen.getByRole("tab", { name: "Artefact preview" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(screen.getByTitle("Preview of report.docx")).toBeInTheDocument();
  });

  it("should move between panel tabs with the arrow keys", async () => {
    const user = userEvent.setup();
    await renderLoadedApp();

    screen.getByRole("tab", { name: "Task list" }).focus();
    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("tab", { name: "Artefact preview" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Artefact preview" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("should show a dismissible alert with message and trace ID when sending fails", async () => {
    orchestrator.setRoute(MESSAGES_ROUTE, () =>
      errorResponse(409, "TURN_IN_PROGRESS", "A turn is already running.")
    );
    const user = userEvent.setup();
    await renderLoadedApp();

    await user.type(screen.getByLabelText("Message"), "Hello{Enter}");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A turn is already running.");
    expect(alert).toHaveTextContent("Trace ID: trace-test-1");
    expect(screen.getByLabelText("Message")).toHaveValue("Hello");

    await user.click(within(alert).getByRole("button", { name: /Dismiss/ }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("should render a stream error inline and let it be dismissed", async () => {
    const user = userEvent.setup();
    await renderLoadedApp();

    act(() =>
      MockEventSource.latest().emit("error", {
        error: "MODEL_FAILED",
        message: "The model stopped responding.",
        trace_id: "trace-77",
      })
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The model stopped responding.");
    expect(alert).toHaveTextContent("trace-77");

    await user.click(within(alert).getByRole("button", { name: /Dismiss/ }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("should upload a dropped file into the session workspace", async () => {
    const uploadRoute = `PUT /api/sessions/${SESSION_ID}/files/brief.txt`;
    orchestrator.setRoute(uploadRoute, emptyResponse);
    await renderLoadedApp();
    const file = new File(["brief"], "brief.txt", { type: "text/plain" });

    fireEvent.drop(screen.getByRole("region", { name: "Conversation" }), {
      dataTransfer: { files: [file], types: ["Files"] },
    });

    expect(await screen.findByText("Added to workspace: brief.txt")).toBeInTheDocument();
    expect(orchestrator.requestsFor(uploadRoute)[0]?.body).toBe(file);
  });

  it("should create a session and subscribe to its event stream", async () => {
    orchestrator.setRoute("GET /api/sessions/session-2/messages", () => jsonResponse([]));
    orchestrator.setRoute("GET /api/sessions/session-2/files", () => jsonResponse([]));
    const user = userEvent.setup();
    await renderLoadedApp();

    await user.click(screen.getByRole("button", { name: "New session" }));

    await waitFor(() =>
      expect(MockEventSource.latest().url).toBe("/api/sessions/session-2/events")
    );
    expect(MockEventSource.instances[0]?.isClosed).toBe(true);
  });

  it("should save an edited memory file and delete one after confirmation", async () => {
    orchestrator.setRoute("PUT /api/memory/preferences.md", emptyResponse);
    orchestrator.setRoute("DELETE /api/memory/preferences.md", emptyResponse);
    const user = userEvent.setup();
    await renderLoadedApp();

    await user.click(screen.getByRole("button", { name: "Memory" }));
    await user.click(await screen.findByRole("button", { name: /Edit preferences.md/ }));
    await user.type(screen.getByLabelText("Content"), " Be brief.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(orchestrator.requestsFor("PUT /api/memory/preferences.md")).toHaveLength(1)
    );
    expect(orchestrator.requestsFor("PUT /api/memory/preferences.md")[0]?.body).toBe(
      JSON.stringify({
        description: "Writing preferences",
        content: "Use British English. Be brief.",
      })
    );

    await user.click(await screen.findByRole("button", { name: /^Delete preferences.md/ }));
    await user.click(screen.getByRole("button", { name: /Confirm delete/ }));

    await waitFor(() =>
      expect(orchestrator.requestsFor("DELETE /api/memory/preferences.md")).toHaveLength(1)
    );
  });

  it("should add a connected folder and reject a relative path", async () => {
    const user = userEvent.setup();
    await renderLoadedApp();

    await user.click(screen.getByText("Connected folders"));
    expect(
      await screen.findByText("C:\\Projects", { selector: ".folder-path" })
    ).toBeInTheDocument();
    const pathInput = screen.getByLabelText("Absolute folder path");

    await user.type(pathInput, "reports");
    await user.click(screen.getByRole("button", { name: "Connect folder" }));

    expect(screen.getByText(/Enter an absolute path/)).toBeInTheDocument();
    expect(orchestrator.requestsFor("PUT /api/folders")).toHaveLength(0);

    await user.clear(pathInput);
    await user.type(pathInput, "D:\\Reports");
    await user.click(screen.getByRole("button", { name: "Connect folder" }));

    await waitFor(() => expect(orchestrator.requestsFor("PUT /api/folders")).toHaveLength(1));
    expect(orchestrator.requestsFor("PUT /api/folders")[0]?.body).toBe(
      JSON.stringify({ folders: ["C:\\Projects", "D:\\Reports"] })
    );
  });

  it("should list skills and apply a chosen theme", async () => {
    const user = userEvent.setup();
    await renderLoadedApp();

    await user.click(screen.getByText("Skills"));
    expect(await screen.findByText("summarise-document")).toBeInTheDocument();

    await user.click(screen.getByText("Settings"));
    await user.selectOptions(screen.getByLabelText("Colour theme"), "dark");

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  });
});
