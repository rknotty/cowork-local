import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { KnowledgeGraph } from "../../api/types";
import { IndexMap } from "./index-map";

const GRAPH: KnowledgeGraph = {
  nodes: [
    { id: "C:\\docs\\leave.md", name: "leave.md", chunk_count: 3 },
    { id: "C:\\docs\\holiday.md", name: "holiday.md", chunk_count: 1 },
  ],
  edges: [{ source: "C:\\docs\\holiday.md", target: "C:\\docs\\leave.md", similarity: 0.9 }],
  file_count: 2,
  chunk_count: 4,
};

function mockApi(graph: KnowledgeGraph): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.endsWith("/knowledge/graph") ? graph : [];
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    })
  );
}

describe("IndexMap", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("should draw one dot per file and one line per connection", async () => {
    mockApi(GRAPH);

    const { container } = render(<IndexMap />);

    expect(await screen.findByText("2 files, 1 connections")).toBeInTheDocument();
    expect(container.querySelectorAll(".map-node")).toHaveLength(2);
    expect(container.querySelectorAll(".map-edge")).toHaveLength(1);
    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Knowledge index map: 2 files, 1 connections"
    );
  });

  it("should name each file on hover", async () => {
    mockApi(GRAPH);

    render(<IndexMap />);

    expect(await screen.findByText("leave.md: 3 passages")).toBeInTheDocument();
  });

  it("should explain how to build an index when there is none", async () => {
    mockApi({ nodes: [], edges: [], file_count: 0, chunk_count: 0 });

    render(<IndexMap />);

    expect(await screen.findByText(/No index yet/)).toBeInTheDocument();
  });
});
