import dagre from "dagre";
import type { Edge, Node } from "@xyflow/react";
import { MarkerType, Position } from "@xyflow/react";

import type { MaterializedTask } from "@/types";

export interface StageNodeData extends Record<string, unknown> {
  label: string;
  taskCount: number;
  deferred: boolean;
  pipelines: string[];
}

export type StageNode = Node<StageNodeData>;

const NODE_WIDTH = 200;
const NODE_HEIGHT = 64;

/**
 * Aggregate a preview's materialized tasks into one node per stage (across all
 * matrix cells) and one edge per `needs` relationship.
 */
export function buildStageGraph(tasks: MaterializedTask[]): { nodes: StageNode[]; edges: Edge[] } {
  const order: string[] = [];
  const byStage = new Map<
    string,
    { count: number; deferred: boolean; needs: Set<string>; pipelines: Set<string> }
  >();

  for (const task of tasks) {
    let agg = byStage.get(task.stage);
    if (!agg) {
      agg = { count: 0, deferred: false, needs: new Set(), pipelines: new Set() };
      byStage.set(task.stage, agg);
      order.push(task.stage);
    }
    agg.count += 1;
    if (task.deferred) agg.deferred = true;
    for (const need of task.needs) agg.needs.add(need);
    agg.pipelines.add(task.pipeline_name);
  }

  const nodes: StageNode[] = order.map((stage) => {
    const agg = byStage.get(stage)!;
    return {
      id: stage,
      type: "stage",
      position: { x: 0, y: 0 },
      data: { label: stage, taskCount: agg.count, deferred: agg.deferred, pipelines: [...agg.pipelines] },
    };
  });

  const edges: Edge[] = [];
  const seen = new Set<string>();
  for (const stage of order) {
    const agg = byStage.get(stage)!;
    for (const need of agg.needs) {
      if (!byStage.has(need)) continue;
      const id = `${need}->${stage}`;
      if (seen.has(id)) continue;
      seen.add(id);
      edges.push({
        id,
        source: need,
        target: stage,
        markerEnd: { type: MarkerType.ArrowClosed, width: 24, height: 24 },
      });
    }
  }

  return { nodes, edges };
}

/** Left-to-right dagre layout (mirrors the pipeline graph layout). */
export function layoutStageGraph(nodes: StageNode[], edges: Edge[]): StageNode[] {
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
      position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
    };
  });
}
