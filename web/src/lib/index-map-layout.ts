import type { KnowledgeAccessPayload, KnowledgeGraph } from "../api/types";

/** The map is drawn in a square viewBox of this size and scales to fit. */
export const MAP_SIZE = 300;
export const MAP_CENTRE = MAP_SIZE / 2;
const RING_RADIUS = 118;
const MIN_DOT_RADIUS = 2.2;
const MAX_DOT_RADIUS = 6;
// How far each connection's curve is pulled towards the centre. Bundling the
// lines inward keeps a dense map readable instead of a tangle of chords.
const CURVE_PULL = 0.55;

export interface PlacedNode {
  id: string;
  name: string;
  chunkCount: number;
  x: number;
  y: number;
  radius: number;
}

export interface PlacedEdge {
  key: string;
  source: string;
  target: string;
  path: string;
  similarity: number;
}

export interface MapLayout {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  nodesById: Map<string, PlacedNode>;
}

const round = (value: number): number => Math.round(value * 10) / 10;

/**
 * Places files evenly around a circle, in the order the orchestrator chose
 * (similar files adjacent), sized by how many passages each holds.
 *
 * @param graph - The index graph
 * @returns Node positions, curved edge paths and a lookup by file path
 */
export function layoutIndexMap(graph: KnowledgeGraph): MapLayout {
  const count = graph.nodes.length;
  const largest = Math.max(1, ...graph.nodes.map((node) => node.chunk_count));
  const nodes = graph.nodes.map((node, index): PlacedNode => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(count, 1);
    const scale = Math.sqrt(node.chunk_count / largest);
    return {
      id: node.id,
      name: node.name,
      chunkCount: node.chunk_count,
      x: round(MAP_CENTRE + RING_RADIUS * Math.cos(angle)),
      y: round(MAP_CENTRE + RING_RADIUS * Math.sin(angle)),
      radius: round(MIN_DOT_RADIUS + (MAX_DOT_RADIUS - MIN_DOT_RADIUS) * scale),
    };
  });
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const edges = graph.edges.flatMap((edge): PlacedEdge[] => {
    const from = nodesById.get(edge.source);
    const to = nodesById.get(edge.target);
    if (from === undefined || to === undefined) {
      return [];
    }
    return [
      {
        key: `${edge.source}\u0000${edge.target}`,
        source: edge.source,
        target: edge.target,
        path: curvePath(from, to),
        similarity: edge.similarity,
      },
    ];
  });
  return { nodes, edges, nodesById };
}

function curvePath(from: PlacedNode, to: PlacedNode): string {
  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2;
  const controlX = round(midX + (MAP_CENTRE - midX) * CURVE_PULL);
  const controlY = round(midY + (MAP_CENTRE - midY) * CURVE_PULL);
  return `M ${from.x} ${from.y} Q ${controlX} ${controlY} ${to.x} ${to.y}`;
}

/**
 * The straight line a retrieved passage travels: from its file to the centre,
 * where the model sits. Drawn file-to-centre so the flow animation reads as
 * data being pulled in.
 *
 * @param node - A retrieved file
 * @returns An SVG path
 */
export function flowPath(node: PlacedNode): string {
  return `M ${node.x} ${node.y} L ${MAP_CENTRE} ${MAP_CENTRE}`;
}

export interface AccessHighlight {
  accessedIds: Set<string>;
  /** Edges between two files the search drew from. */
  litEdgeKeys: Set<string>;
}

/**
 * Works out what a search lights up: the files it drew from, and every
 * connection whose two ends were both drawn from.
 *
 * @param layout - The current map
 * @param access - The latest search, or null before any
 * @returns Sets of node IDs and edge keys to illuminate
 */
export function highlightFor(
  layout: MapLayout,
  access: KnowledgeAccessPayload | null
): AccessHighlight {
  const accessedIds = new Set(
    (access?.files ?? []).map((file) => file.file_path).filter((id) => layout.nodesById.has(id))
  );
  const litEdgeKeys = new Set(
    layout.edges
      .filter((edge) => accessedIds.has(edge.source) && accessedIds.has(edge.target))
      .map((edge) => edge.key)
  );
  return { accessedIds, litEdgeKeys };
}

/**
 * Plain-English summary of a search, shown under the map and announced to
 * screen readers so the visual is never the only record.
 *
 * @param access - The latest search
 * @param layout - The current map, for file names
 * @returns For example "Search "leave policy" drew on 2 files: leave.md (2), travel.md (1)"
 */
export function describeAccess(access: KnowledgeAccessPayload, layout: MapLayout): string {
  if (access.files.length === 0) {
    return `Search “${access.query}” found nothing in the index.`;
  }
  const names = access.files.map((file) => {
    const name = layout.nodesById.get(file.file_path)?.name ?? file.file_path;
    return `${name} (${file.passage_count})`;
  });
  const noun = access.files.length === 1 ? "file" : "files";
  return `Search “${access.query}” drew on ${access.files.length} ${noun}: ${names.join(", ")}`;
}
