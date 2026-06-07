"use client";

import { useEffect, useMemo, useState } from "react";
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

import type { PipelineSummary, ProcessSummary } from "@/types";
import { buildPipelineGraph, layoutGraph, type PipelineNodeData } from "@/lib/pipelineGraph";

function InputNode({ data }: NodeProps) {
  const node = data as PipelineNodeData;
  return (
    <div className="w-[180px] overflow-hidden rounded-md border border-slate-300 bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm">
      <Handle type="target" position={Position.Left} className="!bg-slate-400" />
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">input</div>
      <div className="truncate font-mono text-slate-900" title={node.label}>{node.label}</div>
      <Handle type="source" position={Position.Right} className="!bg-slate-400" />
    </div>
  );
}

function ProcessNode({ data, selected }: NodeProps) {
  const node = data as PipelineNodeData;
  return (
    <div
      className={`w-[180px] overflow-hidden rounded-md border bg-white px-3 py-2 text-xs shadow-sm ${
        selected ? "border-cyan-700 ring-2 ring-cyan-200" : "border-cyan-600"
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-cyan-600" />
      <div className="truncate font-mono font-semibold text-slate-900" title={node.label}>{node.label}</div>
      {node.method ? <div className="mt-0.5 truncate text-[11px] text-slate-500" title={node.method}>{node.method}</div> : null}
      <Handle type="source" position={Position.Right} className="!bg-cyan-600" />
    </div>
  );
}

function OutputNode({ data }: NodeProps) {
  const node = data as PipelineNodeData;
  return (
    <div className="w-[180px] overflow-hidden rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800 shadow-sm">
      <Handle type="target" position={Position.Left} className="!bg-emerald-400" />
      <div className="text-[10px] font-semibold uppercase tracking-wide text-emerald-500">output</div>
      <div className="truncate font-mono text-emerald-900" title={node.label}>{node.label}</div>
      <Handle type="source" position={Position.Right} className="!bg-emerald-400" />
    </div>
  );
}

export const nodeTypes: NodeTypes = {
  input: InputNode,
  process: ProcessNode,
  output: OutputNode,
};

function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

interface Props {
  pipeline: PipelineSummary;
}

export default function PipelineSchematic({ pipeline }: Props) {
  const { laidNodes, builtEdges } = useMemo(() => {
    const { nodes, edges } = buildPipelineGraph(pipeline);
    return { laidNodes: layoutGraph(nodes, edges), builtEdges: edges };
  }, [pipeline]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laidNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(builtEdges);
  const [selected, setSelected] = useState<ProcessSummary | null>(null);

  useEffect(() => {
    setNodes(laidNodes);
    setEdges(builtEdges);
    setSelected(null);
  }, [laidNodes, builtEdges, setNodes, setEdges]);

  return (
    <div className="grid gap-3">
      <div className="h-[480px] rounded-md border border-slate-200 bg-white">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_, node) => {
            const data = node.data as PipelineNodeData;
            setSelected(data.kind === "process" ? data.process ?? null : null);
          }}
          onPaneClick={() => setSelected(null)}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
      {selected ? (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
          <div className="font-mono font-semibold text-slate-900">{selected.name}</div>
          <div className="mt-1 text-xs text-slate-500">
            {selected.package}.{selected.method}
          </div>
          {Object.keys(selected.parameters).length > 0 ? (
            <dl className="mt-2 grid gap-1">
              {Object.entries(selected.parameters).map(([key, value]) => (
                <div key={key} className="flex gap-2 text-xs">
                  <dt className="font-semibold text-slate-600">{key}</dt>
                  <dd className="font-mono text-slate-700">{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="mt-2 text-xs text-slate-500">No parameters.</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-slate-500">Click a process node to inspect its method and parameters.</p>
      )}
    </div>
  );
}
