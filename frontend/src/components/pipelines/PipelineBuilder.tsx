"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type XYPosition,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {
  buildPipelineGraph,
  draftToSummary,
  layoutGraph,
  REFERENCE_PARAMETER_NAMES,
  type PipelineNode,
} from "@/lib/pipelineGraph";
import {
  isPayloadRefKey,
  type InputDraft,
  type OutputDraft,
  type PipelineDraft,
  type ProcessDraft,
} from "@/lib/pipelineDraft";
import { nodeTypes } from "./PipelineSchematic";

type Selection = { type: "node"; id: string } | { type: "edge"; edge: Edge } | null;
type ParamRow = { key: string; value: string };

const inputBase = "h-8 w-full rounded-md border border-slate-300 px-2 text-xs text-slate-950";
const labelBase = "grid gap-1 text-[11px] font-semibold text-slate-500";
const buttonBase = "rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700";

function splitId(id: string): { kind: string; name: string } {
  const index = id.indexOf(":");
  return { kind: id.slice(0, index), name: id.slice(index + 1) };
}

function uniqueName(base: string, taken: Set<string>): string {
  if (!taken.has(base)) return base;
  let i = 2;
  while (taken.has(`${base}_${i}`)) i += 1;
  return `${base}_${i}`;
}

/** Best-effort cell parsing: JSON for numbers/lists/objects/bools, raw string otherwise. */
function parseCell(raw: string): unknown {
  const trimmed = raw.trim();
  if (trimmed === "") return "";
  try {
    return JSON.parse(trimmed);
  } catch {
    return raw;
  }
}

function cellToString(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function rowsToRecord(rows: ParamRow[]): Record<string, unknown> {
  const record: Record<string, unknown> = {};
  for (const row of rows) {
    if (row.key.trim() === "") continue;
    record[row.key] = parseCell(row.value);
  }
  return record;
}

function recordToRows(record: Record<string, unknown>): ParamRow[] {
  return Object.entries(record).map(([key, value]) => ({ key, value: cellToString(value) }));
}

/** Rewrite payload references when a producing input/process is renamed. */
function rewriteReferences(draft: PipelineDraft, oldName: string, newName: string): PipelineDraft {
  return {
    ...draft,
    processes: draft.processes.map((process) => ({
      ...process,
      parameters: Object.fromEntries(
        Object.entries(process.parameters).map(([key, value]) =>
          isPayloadRefKey(key) && value === oldName ? [key, newName] : [key, value],
        ),
      ),
    })),
    outputs: draft.outputs.map((output) => (output.name === oldName ? { ...output, name: newName } : output)),
  };
}

function dropReferences(draft: PipelineDraft, name: string): PipelineDraft {
  return {
    ...draft,
    processes: draft.processes.map((process) => ({
      ...process,
      parameters: Object.fromEntries(
        Object.entries(process.parameters).filter(
          ([key, value]) => !(isPayloadRefKey(key) && value === name),
        ),
      ),
    })),
    outputs: draft.outputs.filter((output) => output.name !== name),
  };
}

interface Props {
  draft: PipelineDraft;
  onChange: (next: PipelineDraft) => void;
}

export default function PipelineBuilder({ draft, onChange }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<PipelineNode>([]);
  const [edges, setEdges] = useEdgesState([] as Edge[]);
  const [selection, setSelection] = useState<Selection>(null);
  const positions = useRef<Map<string, XYPosition>>(new Map());

  // Rebuild the canvas whenever the draft changes (text edit or our own edit),
  // preserving any positions the user dragged.
  useEffect(() => {
    const graph = buildPipelineGraph(draftToSummary(draft));
    const laid = layoutGraph(graph.nodes, graph.edges).map((node) => {
      const saved = positions.current.get(node.id);
      return saved ? { ...node, position: saved } : node;
    });
    setNodes(laid);
    setEdges(graph.edges);
  }, [draft, setNodes, setEdges]);

  const handleNodesChange = useCallback<typeof onNodesChange>(
    (changes) => {
      onNodesChange(changes);
      for (const change of changes) {
        if (change.type === "position" && change.position) {
          positions.current.set(change.id, change.position);
        }
      }
    },
    [onNodesChange],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const { source, target } = connection;
      if (!source || !target || !target.startsWith("proc:")) return;
      const sourceName = splitId(source).name;
      const procName = splitId(target).name;
      const next = structuredClone(draft);
      const process = next.processes.find((item) => item.name === procName);
      if (!process) return;
      let key = REFERENCE_PARAMETER_NAMES.has(sourceName) ? sourceName : "df";
      if (process.parameters[key] !== undefined) {
        let i = 2;
        while (process.parameters[`${key}_${i}`] !== undefined) i += 1;
        key = `${key}_${i}`;
      }
      process.parameters[key] = sourceName;
      onChange(next);
    },
    [draft, onChange],
  );

  const addInput = useCallback(() => {
    const taken = new Set(draft.inputs.map((input) => input.name));
    const name = uniqueName("input", taken);
    const input: InputDraft = { name, src: "EMPTY", package: "", method: "", extras: {} };
    onChange({ ...draft, inputs: [...draft.inputs, input] });
    setSelection({ type: "node", id: `input:${name}` });
  }, [draft, onChange]);

  const addProcess = useCallback(() => {
    const taken = new Set(draft.processes.map((process) => process.name));
    const name = uniqueName("process", taken);
    const process: ProcessDraft = { name, package: "", method: "", parameters: {} };
    onChange({ ...draft, processes: [...draft.processes, process] });
    setSelection({ type: "node", id: `proc:${name}` });
  }, [draft, onChange]);

  const addOutput = useCallback(() => {
    const producer = draft.processes.at(-1)?.name ?? draft.inputs.at(-1)?.name ?? "result";
    const taken = new Set(draft.outputs.map((output) => output.name));
    const name = uniqueName(producer, taken);
    const output: OutputDraft = { name, path: `${name}.csv` };
    onChange({ ...draft, outputs: [...draft.outputs, output] });
    setSelection({ type: "node", id: `output:${name}` });
  }, [draft, onChange]);

  const deleteSelection = useCallback(() => {
    if (!selection) return;
    if (selection.type === "edge") {
      const edge = selection.edge;
      if (edge.target.startsWith("proc:") && typeof edge.label === "string") {
        const procName = splitId(edge.target).name;
        const next = structuredClone(draft);
        const process = next.processes.find((item) => item.name === procName);
        if (process) delete process.parameters[edge.label];
        onChange(next);
      }
      setSelection(null);
      return;
    }
    const { kind, name } = splitId(selection.id);
    let next: PipelineDraft;
    if (kind === "input") {
      next = dropReferences({ ...draft, inputs: draft.inputs.filter((i) => i.name !== name) }, name);
    } else if (kind === "proc") {
      next = dropReferences({ ...draft, processes: draft.processes.filter((p) => p.name !== name) }, name);
    } else {
      next = { ...draft, outputs: draft.outputs.filter((o) => o.name !== name) };
    }
    onChange(next);
    setSelection(null);
  }, [selection, draft, onChange]);

  const selectedNode = selection?.type === "node" ? splitId(selection.id) : null;

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_280px]">
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <button className={buttonBase} onClick={addInput}>
            + Input
          </button>
          <button className={buttonBase} onClick={addProcess}>
            + Process
          </button>
          <button className={buttonBase} onClick={addOutput}>
            + Output
          </button>
          <button
            className="rounded-md border border-red-200 px-2.5 py-1.5 text-xs font-semibold text-red-700 disabled:opacity-40"
            onClick={deleteSelection}
            disabled={!selection}
          >
            Delete selected
          </button>
        </div>
        <div className="h-[460px] rounded-md border border-slate-200 bg-white">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={handleNodesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelection({ type: "node", id: node.id })}
            onEdgeClick={(_, edge) => setSelection({ type: "edge", edge })}
            onPaneClick={() => setSelection(null)}
            deleteKeyCode={null}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>
        <p className="text-[11px] text-slate-500">
          Drag handle to handle to wire a payload into a process. Click a node to edit it, or an edge then
          Delete to remove a reference.
        </p>
      </div>
      <NodeForm key={selection?.type === "node" ? selection.id : "none"} node={selectedNode} draft={draft} onChange={onChange} />
    </div>
  );
}

interface NodeFormProps {
  node: { kind: string; name: string } | null;
  draft: PipelineDraft;
  onChange: (next: PipelineDraft) => void;
}

function NodeForm({ node, draft, onChange }: NodeFormProps) {
  const [rows, setRows] = useState<ParamRow[]>([]);

  const input = node?.kind === "input" ? draft.inputs.find((i) => i.name === node.name) ?? null : null;
  const process = node?.kind === "proc" ? draft.processes.find((p) => p.name === node.name) ?? null : null;
  const output = node?.kind === "output" ? draft.outputs.find((o) => o.name === node.name) ?? null : null;

  // Load the editable parameter/extra rows when the selected node changes.
  useEffect(() => {
    if (process) setRows(recordToRows(process.parameters));
    else if (input) setRows(recordToRows(input.extras));
    else setRows([]);
    // Only re-seed when the selected node identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node?.kind, node?.name]);

  if (!node) {
    return (
      <aside className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
        Select a node to edit its fields, or use the toolbar to add one.
      </aside>
    );
  }

  function renameInput(newName: string) {
    if (!input) return;
    const trimmed = newName.trim();
    if (trimmed === "" || trimmed === input.name) {
      onChange({ ...draft, inputs: draft.inputs.map((i) => (i === input ? { ...i, name: newName } : i)) });
      return;
    }
    const renamed = { ...draft, inputs: draft.inputs.map((i) => (i === input ? { ...i, name: trimmed } : i)) };
    onChange(rewriteReferences(renamed, input.name, trimmed));
  }

  function patchInput(patch: Partial<InputDraft>) {
    if (!input) return;
    onChange({ ...draft, inputs: draft.inputs.map((i) => (i === input ? { ...i, ...patch } : i)) });
  }

  function renameProcess(newName: string) {
    if (!process) return;
    const trimmed = newName.trim();
    if (trimmed === "" || trimmed === process.name) {
      onChange({ ...draft, processes: draft.processes.map((p) => (p === process ? { ...p, name: newName } : p)) });
      return;
    }
    const renamed = {
      ...draft,
      processes: draft.processes.map((p) => (p === process ? { ...p, name: trimmed } : p)),
    };
    onChange(rewriteReferences(renamed, process.name, trimmed));
  }

  function patchProcess(patch: Partial<ProcessDraft>) {
    if (!process) return;
    onChange({ ...draft, processes: draft.processes.map((p) => (p === process ? { ...p, ...patch } : p)) });
  }

  function patchOutput(patch: Partial<OutputDraft>) {
    if (!output) return;
    onChange({ ...draft, outputs: draft.outputs.map((o) => (o === output ? { ...o, ...patch } : o)) });
  }

  function commitRows(nextRows: ParamRow[]) {
    setRows(nextRows);
    const record = rowsToRecord(nextRows);
    if (process) patchProcess({ parameters: record });
    else if (input) patchInput({ extras: record });
  }

  const showRows = Boolean(process || input);
  const rowsLabel = process ? "Parameters" : "Extra spec keys";

  return (
    <aside className="grid content-start gap-2 rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{node.kind}</div>

      {input ? (
        <>
          <label className={labelBase}>
            name
            <input className={inputBase} value={input.name} onChange={(e) => renameInput(e.target.value)} />
          </label>
          <label className={labelBase}>
            src
            <input className={inputBase} value={input.src} onChange={(e) => patchInput({ src: e.target.value })} />
          </label>
          <label className={labelBase}>
            package
            <input className={inputBase} value={input.package} onChange={(e) => patchInput({ package: e.target.value })} />
          </label>
          <label className={labelBase}>
            method
            <input className={inputBase} value={input.method} onChange={(e) => patchInput({ method: e.target.value })} />
          </label>
        </>
      ) : null}

      {process ? (
        <>
          <label className={labelBase}>
            name
            <input className={inputBase} value={process.name} onChange={(e) => renameProcess(e.target.value)} />
          </label>
          <label className={labelBase}>
            package
            <input className={inputBase} value={process.package} onChange={(e) => patchProcess({ package: e.target.value })} />
          </label>
          <label className={labelBase}>
            method
            <input className={inputBase} value={process.method} onChange={(e) => patchProcess({ method: e.target.value })} />
          </label>
        </>
      ) : null}

      {output ? (
        <>
          <label className={labelBase}>
            name (payload)
            <input
              className={inputBase}
              value={output.name}
              onChange={(e) => patchOutput({ name: e.target.value })}
            />
          </label>
          <label className={labelBase}>
            path
            <input className={inputBase} value={output.path} onChange={(e) => patchOutput({ path: e.target.value })} />
          </label>
        </>
      ) : null}

      {showRows ? (
        <div className="grid gap-1">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-500">{rowsLabel}</span>
            <button className={buttonBase} onClick={() => commitRows([...rows, { key: "", value: "" }])}>
              +
            </button>
          </div>
          {rows.map((row, index) => (
            <div key={index} className="flex items-center gap-1">
              <input
                className={`${inputBase} flex-[2]`}
                placeholder="key"
                value={row.key}
                onChange={(e) =>
                  commitRows(rows.map((r, i) => (i === index ? { ...r, key: e.target.value } : r)))
                }
              />
              <input
                className={`${inputBase} flex-[3] font-mono`}
                placeholder="value"
                value={row.value}
                onChange={(e) =>
                  commitRows(rows.map((r, i) => (i === index ? { ...r, value: e.target.value } : r)))
                }
              />
              <button
                className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700"
                onClick={() => commitRows(rows.filter((_, i) => i !== index))}
                aria-label="remove parameter"
              >
                ×
              </button>
            </div>
          ))}
          {process ? (
            <p className="text-[10px] text-slate-400">
              Keys like df, left_df, *_df referencing a payload draw an edge. Other keys are plain values.
            </p>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
