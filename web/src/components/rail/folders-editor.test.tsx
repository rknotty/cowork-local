import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndexMap } from "../panel/index-map";
import { AlertsProvider } from "../../state/alerts-context";
import { FoldersEditor } from "./folders-editor";

const CHOSEN = "C:\\Users\\example\\Documents\\Policies";

interface Route {
  method: string;
  path: string;
  body: unknown;
}

function stubApi(routes: Route[]): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const route = routes.find(
      (candidate) => candidate.method === method && url.endsWith(candidate.path)
    );
    const status = route?.body === undefined && method !== "GET" ? 204 : 200;
    const body = status === 204 ? null : JSON.stringify(route?.body ?? []);
    return Promise.resolve(new Response(body, { status }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const callsTo = (fetchMock: ReturnType<typeof vi.fn>, path: string): unknown[][] =>
  fetchMock.mock.calls.filter(([input]) => String(input).endsWith(path));

describe("FoldersEditor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("should fill the path from the folder dialog without connecting it yet", async () => {
    const user = userEvent.setup();
    const fetchMock = stubApi([
      { method: "GET", path: "/api/folders", body: { folders: [] } },
      { method: "POST", path: "/api/folders/browse", body: { folder: CHOSEN } },
    ]);
    render(
      <AlertsProvider>
        <FoldersEditor />
      </AlertsProvider>
    );

    await user.click(await screen.findByRole("button", { name: "Browse…" }));

    expect(await screen.findByLabelText("Absolute folder path")).toHaveValue(CHOSEN);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("should leave the field unchanged when the dialog is cancelled", async () => {
    const user = userEvent.setup();
    stubApi([
      { method: "GET", path: "/api/folders", body: { folders: [] } },
      { method: "POST", path: "/api/folders/browse", body: { folder: null } },
    ]);
    render(
      <AlertsProvider>
        <FoldersEditor />
      </AlertsProvider>
    );

    await user.click(await screen.findByRole("button", { name: "Browse…" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Browse…" })).not.toHaveAttribute(
        "aria-busy",
        "true"
      )
    );
    expect(screen.getByLabelText("Absolute folder path")).toHaveValue("");
  });

  it("should refresh the index map straight away when a folder is removed", async () => {
    const user = userEvent.setup();
    const fetchMock = stubApi([
      { method: "GET", path: "/api/folders", body: { folders: ["C:\\Docs"] } },
      { method: "PUT", path: "/api/folders", body: undefined },
      {
        method: "GET",
        path: "/api/knowledge/graph",
        body: { nodes: [], edges: [], file_count: 0, chunk_count: 0 },
      },
    ]);
    render(
      <AlertsProvider>
        <FoldersEditor />
        <IndexMap />
      </AlertsProvider>
    );
    await screen.findByRole("button", { name: /Remove/ });
    await waitFor(() => expect(callsTo(fetchMock, "/api/knowledge/graph")).toHaveLength(1));

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /Remove/ }));
    });

    await waitFor(() => expect(callsTo(fetchMock, "/api/knowledge/graph")).toHaveLength(2));
  });
});
