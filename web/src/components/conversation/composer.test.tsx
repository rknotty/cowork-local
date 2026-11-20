import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FileUpload } from "../../hooks/use-file-upload";
import {
  errorResponse,
  installMockOrchestrator,
  MockEventSource,
  SESSION_ID,
} from "../../test/mock-orchestrator";
import type { MockOrchestrator } from "../../test/mock-orchestrator";
import { renderInSession } from "../../test/render-helpers";
import { Composer } from "./composer";

const MESSAGES_ROUTE = `POST /api/sessions/${SESSION_ID}/messages`;

/** Records nothing real: stopping hands back one fixed chunk, as a browser would. */
class MockMediaRecorder extends EventTarget {
  static isTypeSupported = (): boolean => true;

  readonly stream: MediaStream;

  constructor(stream: MediaStream) {
    super();
    this.stream = stream;
  }

  start(): void {}

  stop(): void {
    const chunk = Object.assign(new Event("dataavailable"), { data: new Blob(["audio"]) });
    this.dispatchEvent(chunk);
    this.dispatchEvent(new Event("stop"));
  }
}

const idleUpload: FileUpload = {
  isUploading: false,
  uploadedNames: [],
  uploadFiles: () => Promise.resolve(),
};

describe("Composer", () => {
  let orchestrator: MockOrchestrator;
  let stopTrack: () => void;

  const stubMicrophone = (getUserMedia: () => Promise<unknown>): void => {
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
  };

  beforeEach(() => {
    orchestrator = installMockOrchestrator();
    stopTrack = vi.fn();
    stubMicrophone(() => Promise.resolve({ getTracks: () => [{ stop: stopTrack }] }));
  });

  it("should put transcribed speech in the box for review and never send it", async () => {
    const user = userEvent.setup();
    renderInSession(<Composer upload={idleUpload} orchestratorModelId="example-model-14b:2" />);

    await user.click(screen.getByRole("button", { name: "Record voice input" }));
    await user.click(await screen.findByRole("button", { name: "Stop recording" }));

    await waitFor(() => expect(screen.getByLabelText("Message")).toHaveValue("transcribed words"));
    const [transcription] = orchestrator.requestsFor("POST /api/transcriptions");
    expect(transcription?.headers["Content-Type"]).toBe("audio/webm");
    expect(orchestrator.requestsFor(MESSAGES_ROUTE)).toHaveLength(0);
    expect(stopTrack).toHaveBeenCalled();
  });

  it("should show a safe message when the microphone is refused", async () => {
    stubMicrophone(() => Promise.reject(new DOMException("Permission denied", "NotAllowedError")));
    const user = userEvent.setup();
    renderInSession(<Composer upload={idleUpload} orchestratorModelId={null} />);

    await user.click(screen.getByRole("button", { name: "Record voice input" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The microphone could not be used.");
    expect(alert).not.toHaveTextContent("Permission denied");
  });

  it("should disable voice input when the browser cannot record", () => {
    vi.stubGlobal("MediaRecorder", undefined);

    renderInSession(<Composer upload={idleUpload} orchestratorModelId={null} />);

    expect(
      screen.getByRole("button", { name: "Voice input is not available in this browser" })
    ).toBeDisabled();
  });

  it("should post once when Enter and the Send button fire in the same tick", async () => {
    const user = userEvent.setup();
    renderInSession(<Composer upload={idleUpload} orchestratorModelId={null} />);
    const messageBox = screen.getByLabelText("Message");
    await user.type(messageBox, "Summarise the report");

    fireEvent.keyDown(messageBox, { key: "Enter" });
    fireEvent.keyDown(messageBox, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(messageBox).toHaveValue(""));
    expect(orchestrator.requestsFor(MESSAGES_ROUTE)).toHaveLength(1);
  });

  it("should keep sending disabled from the send until the turn's done event", async () => {
    const user = userEvent.setup();
    renderInSession(<Composer upload={idleUpload} orchestratorModelId={null} />);
    const messageBox = screen.getByLabelText("Message");
    const sendButton = screen.getByRole("button", { name: "Send" });

    await user.type(messageBox, "First{Enter}");
    await waitFor(() => expect(messageBox).toHaveValue(""));
    await user.type(messageBox, "Second{Enter}");

    expect(sendButton).toBeDisabled();
    expect(messageBox).toHaveValue("Second");
    expect(orchestrator.requestsFor(MESSAGES_ROUTE)).toHaveLength(1);

    act(() => MockEventSource.latest().emit("done", { reason: "answered", model_id: "m:1" }));

    expect(sendButton).toBeEnabled();
    await user.type(messageBox, "{Enter}");
    await waitFor(() => expect(orchestrator.requestsFor(MESSAGES_ROUTE)).toHaveLength(2));
  });

  it("should allow another attempt after a send is rejected", async () => {
    orchestrator.setRoute(MESSAGES_ROUTE, () =>
      errorResponse(400, "TURN_IN_PROGRESS", "A turn is already running.")
    );
    const user = userEvent.setup();
    renderInSession(<Composer upload={idleUpload} orchestratorModelId={null} />);

    await user.type(screen.getByLabelText("Message"), "Hello{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("A turn is already running.");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(screen.getByLabelText("Message")).toHaveValue("Hello");
  });

  it("should add a new line on Shift+Enter instead of sending", async () => {
    const user = userEvent.setup();
    renderInSession(<Composer upload={idleUpload} orchestratorModelId={null} />);

    await user.type(screen.getByLabelText("Message"), "Line one{Shift>}{Enter}{/Shift}Line two");

    expect(screen.getByLabelText("Message")).toHaveValue("Line one\nLine two");
    expect(orchestrator.requestsFor(MESSAGES_ROUTE)).toHaveLength(0);
  });

  it("should show the orchestrator model with its full ID on hover", () => {
    renderInSession(<Composer upload={idleUpload} orchestratorModelId="example-model-14b:2" />);

    expect(screen.getByText("example-model-14b")).toHaveAttribute("title", "example-model-14b:2");
  });

  it("should pass chosen files to the uploader and list uploaded names", async () => {
    const uploadFiles = vi.fn(() => Promise.resolve());
    const upload: FileUpload = { isUploading: false, uploadedNames: ["brief.txt"], uploadFiles };
    const user = userEvent.setup();
    const { container } = renderInSession(<Composer upload={upload} orchestratorModelId={null} />);
    const file = new File(["x"], "data.csv");

    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, file);

    expect(uploadFiles).toHaveBeenCalledWith([file]);
    expect(screen.getByText("Added to workspace: brief.txt")).toBeInTheDocument();
  });
});
