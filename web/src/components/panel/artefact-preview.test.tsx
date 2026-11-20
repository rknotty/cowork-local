import { act, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { ArtefactPayload } from "../../api/types";
import { PREVIEW_CONTENT_SECURITY_POLICY } from "../../lib/artefact-document";
import { installMockOrchestrator, MockEventSource, SESSION_ID } from "../../test/mock-orchestrator";
import type { MockOrchestrator } from "../../test/mock-orchestrator";
import { renderInSession } from "../../test/render-helpers";
import { ArtefactPreview } from "./artefact-preview";

const fileRoute = (relativePath: string): string =>
  `GET /api/sessions/${SESSION_ID}/files/${relativePath}`;

const textResponse = (body: string): Response => new Response(body, { status: 200 });

describe("ArtefactPreview", () => {
  let orchestrator: MockOrchestrator;

  const renderWithArtefact = (artefact: ArtefactPayload): void => {
    renderInSession(<ArtefactPreview />);
    act(() => MockEventSource.latest().emit("artefact", artefact));
  };

  beforeEach(() => {
    orchestrator = installMockOrchestrator();
  });

  it("should explain that previews appear here before any artefact exists", () => {
    renderInSession(<ArtefactPreview />);

    expect(screen.getByText(/will be previewed here/)).toBeInTheDocument();
  });

  it("should render an HTML artefact in a script-only sandbox with the CSP injected", async () => {
    orchestrator.setRoute(fileRoute("page.html"), () =>
      textResponse("<!doctype html><html><body><h1>Report</h1></body></html>")
    );

    renderWithArtefact({ relative_path: "page.html", kind: "html", preview_path: null });

    const frame = await screen.findByTitle("Preview of page.html");
    const srcdoc = frame.getAttribute("srcdoc") ?? "";
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame).not.toHaveAttribute("src");
    expect(srcdoc).toContain(
      `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CONTENT_SECURITY_POLICY}">`
    );
    expect(srcdoc.indexOf("Content-Security-Policy")).toBeLessThan(srcdoc.indexOf("<html>"));
  });

  it("should render an SVG artefact in the same sandbox", async () => {
    orchestrator.setRoute(fileRoute("chart.svg"), () => textResponse("<svg><circle r='4'/></svg>"));

    renderWithArtefact({ relative_path: "chart.svg", kind: "svg", preview_path: null });

    const frame = await screen.findByTitle("Preview of chart.svg");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame.getAttribute("srcdoc")).toContain("Content-Security-Policy");
  });

  it("should render a markdown artefact natively", async () => {
    orchestrator.setRoute(fileRoute("notes.md"), () => textResponse("# Findings\n\nAll good."));

    renderWithArtefact({ relative_path: "notes.md", kind: "markdown", preview_path: null });

    expect(await screen.findByRole("heading", { name: "Findings" })).toBeInTheDocument();
  });

  it("should show the PDF render of an office document with a download link to the original", () => {
    renderWithArtefact({
      relative_path: "report.docx",
      kind: "docx",
      preview_path: "previews/report.pdf",
    });

    expect(screen.getByTitle("Preview of report.docx")).toHaveAttribute(
      "src",
      `/api/sessions/${SESSION_ID}/files/previews/report.pdf`
    );
    expect(screen.getByRole("link", { name: /Download/ })).toHaveAttribute(
      "href",
      `/api/sessions/${SESSION_ID}/files/report.docx`
    );
  });

  it("should show a PNG render as an image", () => {
    renderWithArtefact({
      relative_path: "deck.pptx",
      kind: "pptx",
      preview_path: "previews/deck.png",
    });

    expect(screen.getByRole("img", { name: "Rendered preview of deck.pptx" })).toHaveAttribute(
      "src",
      `/api/sessions/${SESSION_ID}/files/previews/deck.png`
    );
  });

  it("should say plainly when no preview render exists and still offer the download", () => {
    renderWithArtefact({ relative_path: "figures.xlsx", kind: "xlsx", preview_path: null });

    expect(screen.getByText(/No preview render is available/)).toBeInTheDocument();
    expect(
      screen.getByText(/sandbox that produces renders may be unavailable/)
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download/ })).toHaveAttribute(
      "href",
      `/api/sessions/${SESSION_ID}/files/figures.xlsx`
    );
  });
});
