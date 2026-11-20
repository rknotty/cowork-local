import { useMemo } from "react";
import type { ReactElement } from "react";
import type { KnowledgeAccessPayload } from "../../api/types";
import { useKnowledgeGraph } from "../../hooks/use-knowledge-graph";
import {
  describeAccess,
  flowPath,
  highlightFor,
  layoutIndexMap,
  MAP_CENTRE,
  MAP_SIZE,
} from "../../lib/index-map-layout";
import type { AccessHighlight, MapLayout } from "../../lib/index-map-layout";
import { useOptionalSession } from "../../state/session-context";

interface MapLayerProps {
  layout: MapLayout;
  highlight: AccessHighlight;
}

/** Every connection and file, always drawn; accessed files keep a ring. */
function BaseLayer({ layout, highlight }: MapLayerProps): ReactElement {
  return (
    <g>
      {layout.edges.map((edge) => (
        <path key={edge.key} className="map-edge" d={edge.path} />
      ))}
      {layout.nodes.map((node) => (
        <circle
          key={node.id}
          className={highlight.accessedIds.has(node.id) ? "map-node is-last-accessed" : "map-node"}
          cx={node.x}
          cy={node.y}
          r={node.radius}
        >
          <title>{`${node.name}: ${node.chunkCount} passages`}</title>
        </circle>
      ))}
    </g>
  );
}

/**
 * The illumination for one search. Re-keyed by search sequence so the
 * animation replays on every search, even a repeat of the same query.
 */
function AccessLayer({ layout, highlight }: MapLayerProps): ReactElement {
  const accessedNodes = layout.nodes.filter((node) => highlight.accessedIds.has(node.id));
  return (
    <g className="map-access" aria-hidden="true">
      {layout.edges
        .filter((edge) => highlight.litEdgeKeys.has(edge.key))
        .map((edge) => (
          <path key={edge.key} className="map-edge-lit" d={edge.path} />
        ))}
      {accessedNodes.map((node) => (
        <path key={`flow-${node.id}`} className="map-flow" d={flowPath(node)} />
      ))}
      {accessedNodes.map((node) => (
        <circle
          key={node.id}
          className="map-node-lit"
          cx={node.x}
          cy={node.y}
          r={node.radius + 2}
        />
      ))}
      <circle className="map-hub-pulse" cx={MAP_CENTRE} cy={MAP_CENTRE} r={8} />
    </g>
  );
}

interface IndexMapCanvasProps {
  layout: MapLayout;
  access: { sequence: number; payload: KnowledgeAccessPayload } | null;
  summary: string;
}

function IndexMapCanvas({ layout, access, summary }: IndexMapCanvasProps): ReactElement {
  const highlight = highlightFor(layout, access?.payload ?? null);
  return (
    <svg
      className="index-map-canvas"
      viewBox={`0 0 ${MAP_SIZE} ${MAP_SIZE}`}
      role="img"
      aria-label={summary}
    >
      <BaseLayer layout={layout} highlight={highlight} />
      {access !== null && (
        <AccessLayer key={access.sequence} layout={layout} highlight={highlight} />
      )}
      <circle className="map-hub" cx={MAP_CENTRE} cy={MAP_CENTRE} r={4} />
    </svg>
  );
}

// Loading and empty are different states: saying "no index" before the
// first response arrives would be wrong whenever an index exists.
function emptyMessage(isLoading: boolean, isBuilding: boolean): string {
  if (isBuilding) {
    return "Building the index. Files appear here as they are processed.";
  }
  if (isLoading) {
    return "Loading the index map…";
  }
  return "No index yet. Connect a folder in the left rail to build one.";
}

function mapSummary(fileCount: number, edgeCount: number, isBuilding: boolean): string {
  const prefix = isBuilding ? "Building: " : "";
  return `${prefix}${fileCount} files, ${edgeCount} connections`;
}

/**
 * Live map of the knowledge index: one dot per file around a circle, lines
 * between files whose content is close, and an illumination each time a
 * search draws passages from them.
 */
export function IndexMap(): ReactElement {
  const { graph, isBuilding } = useKnowledgeGraph();
  const access = useOptionalSession()?.state.knowledgeAccess ?? null;
  const layout = useMemo(() => (graph === null ? null : layoutIndexMap(graph)), [graph]);

  return (
    <section className="index-map" aria-labelledby="index-map-heading">
      <h2 id="index-map-heading" className="index-map-heading">
        Knowledge index
        {layout !== null && (
          <span className="index-map-counts">
            {mapSummary(layout.nodes.length, layout.edges.length, isBuilding)}
          </span>
        )}
      </h2>
      {layout === null || layout.nodes.length === 0 ? (
        <p className="empty-state">{emptyMessage(layout === null, isBuilding)}</p>
      ) : (
        <>
          <IndexMapCanvas
            layout={layout}
            access={access}
            summary={`Knowledge index map: ${mapSummary(layout.nodes.length, layout.edges.length, isBuilding)}`}
          />
          <p className="index-map-caption" role="status">
            {access === null
              ? "Searches by the model light up the files they draw from."
              : describeAccess(access.payload, layout)}
          </p>
        </>
      )}
    </section>
  );
}
