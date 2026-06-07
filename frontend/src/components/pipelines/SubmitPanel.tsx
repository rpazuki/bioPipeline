"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
import YamlTreeView from "@/components/pipelines/YamlTreeView";
import { getPipelineYaml, getPipelineYamlTree, submitJob } from "@/lib/api";
import type { YamlTreeNode } from "@/types";

interface Props {
  yamlName: string;
  pipelineNames: string[];
  yamlIsValid: boolean;
  yamlError: string | null;
  onYamlSelect: (payload: { name: string; content: string; pipelines: string[]; isValid: boolean; error: string | null }) => void;
  onStatus: (message: string) => void;
}

function findNode(nodes: YamlTreeNode[], path: string): YamlTreeNode | null {
  for (const node of nodes) {
    if (node.path === path) return node;
    const nested = findNode(node.children, path);
    if (nested) return nested;
  }
  return null;
}

function parseOverrides(value: string) {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .reduce<Record<string, string>>((acc, pair) => {
      const index = pair.indexOf("=");
      if (index > 0) acc[pair.slice(0, index).trim()] = pair.slice(index + 1).trim();
      return acc;
    }, {});
}

export default function SubmitPanel({ yamlName, pipelineNames, yamlIsValid, onYamlSelect, onStatus }: Props) {
  const router = useRouter();
  const [tree, setTree] = useState<YamlTreeNode[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [pipelineName, setPipelineName] = useState("");
  const [outputDir, setOutputDir] = useState("./outputs/run-001");
  const [scheduledAt, setScheduledAt] = useState("");
  const [inputOverrides, setInputOverrides] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pipelineName && pipelineNames.length) setPipelineName(pipelineNames[0]);
  }, [pipelineNames, pipelineName]);

  useEffect(() => {
    setSelectedPath(yamlName);
  }, [yamlName]);

  async function refreshTree() {
    setTree(await getPipelineYamlTree());
  }

  useEffect(() => {
    refreshTree().catch((cause: Error) => {
      setError(cause.message);
      onStatus(cause.message);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function selectNode(node: YamlTreeNode) {
    setSelectedPath(node.path);
    if (node.node_type !== "file") {
      return;
    }
    const document = await getPipelineYaml(node.path);
    onYamlSelect({
      name: document.name,
      content: document.content,
      pipelines: document.pipelines,
      isValid: document.is_valid,
      error: document.error ?? null,
    });
    onStatus(document.is_valid ? `Selected ${document.name}` : `Selected ${document.name}; invalid YAML`);
  }

  async function navigatePath(path: string) {
    if (!path) {
      setSelectedPath("");
      onStatus("Selected root folder");
      return;
    }
    const node = findNode(tree, path);
    if (!node) {
      throw new Error(`Path not found: ${path}`);
    }
    await selectNode(node);
  }

  async function submit() {
    const job = await submitJob({
      yaml_name: yamlName,
      pipeline_name: pipelineName || pipelineNames[0] || "",
      output_dir: outputDir,
      input_sources: parseOverrides(inputOverrides),
      scheduled_at: scheduledAt || null,
    });
    onStatus(`Submitted job ${job.id} — see the Job Queue`);
    router.push("/");
  }

  const canSubmit = Boolean(yamlName && yamlIsValid && pipelineNames.length);

  return (
    <section className="grid gap-4 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">Submit a Job</h2>
          <p className="mt-1 text-xs text-slate-500">
            Select a YAML from the tree, choose a pipeline, then submit. Track it on the Job Queue page.
          </p>
        </div>
        <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={() => refreshTree().catch((cause: Error) => setError(cause.message))}>
          Refresh tree
        </button>
      </div>

      {error ? <p className="text-xs text-rose-700">{error}</p> : null}

      <ResizableSplitPane
        defaultSplit={42}
        left={
          <div className="grid self-start gap-3 pr-2">
            <YamlTreeView
              nodes={tree}
              selectedPath={selectedPath}
              onSelect={(node) => selectNode(node).catch((cause: Error) => setError(cause.message))}
              onNavigatePath={(path) => navigatePath(path).catch((cause: Error) => setError(cause.message))}
            />
          </div>
        }
        right={
          <div className="grid gap-4 pl-2">
            <div className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-slate-950">Pipeline Controls</h3>
                <p className="mt-1 text-xs text-slate-500">Submit a single-pipeline job. Use Job Definitions for multi-stage runs.</p>
              </div>
              <button
                className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40"
                onClick={() => submit().catch((cause: Error) => setError(cause.message))}
                disabled={!canSubmit}
              >
                Submit Job
              </button>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-1 text-xs font-semibold text-slate-500 md:col-span-2">
                Pipeline
                <select
                  className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
                  value={pipelineName}
                  onChange={(event) => setPipelineName(event.target.value)}
                  disabled={!pipelineNames.length}
                >
                  {pipelineNames.length === 0 ? <option value="">Select a valid YAML first</option> : null}
                  {pipelineNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1 text-xs font-semibold text-slate-500 md:col-span-2">
                Output directory
                <input className="h-9 rounded-md border border-slate-300 px-3 text-sm" value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
              </label>
              <label className="grid gap-1 text-xs font-semibold text-slate-500">
                Run at
                <input className="h-9 rounded-md border border-slate-300 px-3 text-sm" placeholder="2026-06-05T18:30:00+00:00" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} />
              </label>
              <label className="grid gap-1 text-xs font-semibold text-slate-500">
                Input overrides
                <input className="h-9 rounded-md border border-slate-300 px-3 text-sm" placeholder="raw_data=./raw.csv, meta_data=./meta.csv" value={inputOverrides} onChange={(event) => setInputOverrides(event.target.value)} />
              </label>
            </div>
          </div>
        }
      />
    </section>
  );
}
