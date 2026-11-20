import { describe, expect, it } from "vitest";
import type { KnowledgeGraph } from "../api/types";
import {
  describeAccess,
  flowPath,
  highlightFor,
  layoutIndexMap,
  MAP_CENTRE,
} from "./index-map-layout";

const GRAPH: KnowledgeGraph = {
  nodes: [
    { id: "C:\\docs\\leave.md", name: "leave.md", chunk_count: 4 },
    { id: "C:\\docs\\holiday.md", name: "holiday.md", chunk_count: 1 },
    { id: "C:\\docs\\travel.md", name: "travel.md", chunk_count: 2 },
    { id: "C:\\docs\\rail.md", name: "rail.md", chunk_count: 2 },
  ],
  edges: [
    { source: "C:\\docs\\holiday.md", target: "C:\\docs\\leave.md", similarity: 0.9 },
    { source: "C:\\docs\\rail.md", target: "C:\\docs\\travel.md", similarity: 0.8 },
    { source: "C:\\docs\\leave.md", target: "C:\\docs\\ghost.md", similarity: 0.5 },
  ],
  file_count: 4,
  chunk_count: 9,
};

describe("layoutIndexMap", () => {
  it("should place every file on one circle, first at the top", () => {
    const layout = layoutIndexMap(GRAPH);

    const distances = layout.nodes.map((node) =>
      Math.hypot(node.x - MAP_CENTRE, node.y - MAP_CENTRE)
    );
    expect(new Set(distances.map((distance) => Math.round(distance))).size).toBe(1);
    expect(layout.nodes[0]).toMatchObject({ x: MAP_CENTRE });
    expect(layout.nodes[0]?.y).toBeLessThan(MAP_CENTRE);
  });

  it("should size dots by how many passages each file holds", () => {
    const layout = layoutIndexMap(GRAPH);

    const [leave, holiday] = layout.nodes;
    expect(leave?.radius).toBeGreaterThan(holiday?.radius ?? Infinity);
  });

  it("should drop an edge whose file is not in the graph", () => {
    expect(layoutIndexMap(GRAPH).edges).toHaveLength(2);
  });

  it("should handle an empty index", () => {
    const empty = layoutIndexMap({ nodes: [], edges: [], file_count: 0, chunk_count: 0 });

    expect(empty.nodes).toEqual([]);
    expect(empty.edges).toEqual([]);
  });
});

describe("highlightFor", () => {
  it("should light the files a search used and only the edges between two of them", () => {
    const layout = layoutIndexMap(GRAPH);

    const highlight = highlightFor(layout, {
      query: "annual leave",
      files: [
        { file_path: "C:\\docs\\leave.md", passage_count: 2, best_score: 0.03 },
        { file_path: "C:\\docs\\holiday.md", passage_count: 1, best_score: 0.02 },
        { file_path: "C:\\docs\\travel.md", passage_count: 1, best_score: 0.01 },
      ],
    });

    expect(highlight.accessedIds.size).toBe(3);
    expect([...highlight.litEdgeKeys]).toEqual(["C:\\docs\\holiday.md\u0000C:\\docs\\leave.md"]);
  });

  it("should ignore files that are no longer in the index", () => {
    const highlight = highlightFor(layoutIndexMap(GRAPH), {
      query: "x",
      files: [{ file_path: "C:\\gone.md", passage_count: 1, best_score: 0.1 }],
    });

    expect(highlight.accessedIds.size).toBe(0);
  });
});

describe("describeAccess", () => {
  it("should name the files and passage counts in plain English", () => {
    const layout = layoutIndexMap(GRAPH);

    const text = describeAccess(
      {
        query: "leave",
        files: [{ file_path: "C:\\docs\\leave.md", passage_count: 2, best_score: 0.03 }],
      },
      layout
    );

    expect(text).toBe("Search \u201cleave\u201d drew on 1 file: leave.md (2)");
  });

  it("should say when a search found nothing", () => {
    expect(describeAccess({ query: "x", files: [] }, layoutIndexMap(GRAPH))).toBe(
      "Search \u201cx\u201d found nothing in the index."
    );
  });
});

describe("flowPath", () => {
  it("should run from the file to the centre", () => {
    const [first] = layoutIndexMap(GRAPH).nodes;

    expect(flowPath(first!)).toBe(`M ${first?.x} ${first?.y} L ${MAP_CENTRE} ${MAP_CENTRE}`);
  });
});
