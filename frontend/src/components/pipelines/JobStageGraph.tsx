"use client";

import { useEffect, useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { buildStageGraph, layoutStageGraph, type StageNodeData } from "@/lib/jobStageGraph";
import type { MaterializedTask } from "@/types";

function StageNodeView({ data }: NodeProps) {
  const node = data as StageNodeData;
  return (
    <div
      className={`rounded-md border bg-white px-3 py-2 text-xs shadow-sm ${
        node.deferred ? "border-dashed border-slate-400" : "border-cyan-600"
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-cyan-600" />
      <div className="font-mono font-semibold text-slate-900">{node.label}</div>
      <div className="mt-0.5 text-[11px] text-slate-500">
        {node.taskCount} task{node.taskCount === 1 ? "" : "s"}
        {node.deferred ? " · deferred" : ""}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-cyan-600" />
    </div>
  );
}

const nodeTypes: NodeTypes = { stage: StageNodeView };

export default function JobStageGraph({ tasks }: { tasks: MaterializedTask[] }) {
  const { laidNodes, builtEdges } = useMemo(() => {
    const { nodes, edges } = buildStageGraph(tasks);
    return { laidNodes: layoutStageGraph(nodes, edges), builtEdges: edges };
  }, [tasks]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laidNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(builtEdges);

  useEffect(() => {
    setNodes(laidNodes);
    setEdges(builtEdges);
  }, [laidNodes, builtEdges, setNodes, setEdges]);

  if (tasks.length === 0) {
    return null;
  }

  return (
    <div className="grid gap-1">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Stages</div>
      <div className="h-64 rounded-md border border-slate-200 bg-white">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}
