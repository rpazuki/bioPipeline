import dagre from "dagre";
import type { Edge, Node } from "@xyflow/react";
import { Position } from "@xyflow/react";

import type { PipelineSummary, ProcessSummary } from "@/types";

/**
 * Parameter keys that signal a reference to a prior payload (an input or an
 * earlier process output). Mirrors REFERENCE_PARAMETER_NAMES in the backend
 * (src/bio_pipeline_manager/yaml_validation.py). Any key ending in "_df" also
 * counts, matching the backend's _warn_unknown_payload_references rule.
 */
export const REFERENCE_PARAMETER_NAMES = new Set<string>([
  "df",
  "df_parsed",
  "folders_list",
  "left_df",
  "meta_data",
  "params_df",
  "payload",
  "raw_data",
  "right_df",
]);

export type PipelineNodeKind = "input" | "process" | "output";

export interface PipelineNodeData extends Record<string, unknown> {
  kind: PipelineNodeKind;
  label: string;
  /** Method shown on process nodes. */
  method?: string;
  /** Package + parameters for the detail panel on process nodes. */
  process?: ProcessSummary;
}

export type PipelineNode = Node<PipelineNodeData>;

const NODE_WIDTH = 180;
const NODE_HEIGHT = 52;

function keySuggestsPayload(key: string): boolean {
  return REFERENCE_PARAMETER_NAMES.has(key) || key.endsWith("_df");
}

/**
 * Build React Flow nodes + edges from a validated pipeline summary.
 *
 * Nodes are id-prefixed by kind (`input:`, `proc:`, `output:`) because an
 * output name equals the payload name that produced it, which would otherwise
 * collide. Edges follow data dependencies derived from process parameters and
 * from output → producer links.
 */
export function buildPipelineGraph(pipeline: PipelineSummary): {
  nodes: PipelineNode[];
  edges: Edge[];
} {
  const producers = new Set<string>([
    ...pipeline.inputs,
    ...pipeline.processes.map((process) => process.name),
  ]);

  const nodes: PipelineNode[] = [];

  for (const name of pipeline.inputs) {
    nodes.push({
      id: `input:${name}`,
      type: "input",
      position: { x: 0, y: 0 },
      data: { kind: "input", label: name },
    });
  }

  for (const process of pipeline.processes) {
    nodes.push({
      id: `proc:${process.name}`,
      type: "process",
      position: { x: 0, y: 0 },
      data: {
        kind: "process",
        label: process.name,
        method: process.method,
        process,
      },
    });
  }

  for (const name of pipeline.outputs) {
    nodes.push({
      id: `output:${name}`,
      type: "output",
      position: { x: 0, y: 0 },
      data: { kind: "output", label: name },
    });
  }

  const edges: Edge[] = [];
  const seen = new Set<string>();

  function addEdge(source: string, target: string, label?: string) {
    const id = `${source}->${target}${label ? `:${label}` : ""}`;
    if (seen.has(id)) return;
    seen.add(id);
    edges.push({ id, source, target, label });
  }

  // Process input dependencies, from parameter references.
  for (const process of pipeline.processes) {
    for (const [key, value] of Object.entries(process.parameters)) {
      if (typeof value !== "string") continue;
      if (!keySuggestsPayload(key)) continue;
      if (!producers.has(value)) continue;
      const source = pipeline.inputs.includes(value) ? `input:${value}` : `proc:${value}`;
      addEdge(source, `proc:${process.name}`, key);
    }
  }

  // Output links, from each output back to its producing payload.
  for (const name of pipeline.outputs) {
    if (!producers.has(name)) continue;
    const source = pipeline.inputs.includes(name) ? `input:${name}` : `proc:${name}`;
    addEdge(source, `output:${name}`);
  }

  return { nodes, edges };
}

/**
 * Assign left-to-right positions to nodes using dagre. Process list order is
 * already topological, but dagre also lays out branches/merges cleanly.
 */
export function layoutGraph(nodes: PipelineNode[], edges: Edge[]): PipelineNode[] {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "LR", nodesep: 24, ranksep: 80 });

  for (const node of nodes) {
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    graph.setEdge(edge.source, edge.target);
  }

  dagre.layout(graph);

  return nodes.map((node) => {
    const { x, y } = graph.node(node.id);
    return {
      ...node,
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      // dagre returns the node center; React Flow expects the top-left corner.
      position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
    };
  });
}
