"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import YamlTreeView from "@/components/pipelines/YamlTreeView";
import { cancelJob, deleteJob, getJobLogs, getPipelineYaml, getPipelineYamlTree, getRuntimeInfo, listJobs, rewindJob, runDueJobs, submitJob } from "@/lib/api";
import type { Job, RuntimeInfo, YamlTreeNode } from "@/types";

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

function formatRelativeTime(value: string | null): string {
  if (!value) {
    return "—";
  }
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) {
    return "—";
  }
  const seconds = Math.round((Date.now() - timestamp) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function formatRelativeYamlPath(yamlPath: string, yamlRoot: string | null): string {
  if (!yamlPath) {
    return "—";
  }
  if (yamlRoot) {
    const normalizedRoot = yamlRoot.replace(/\/+$/, "");
    if (yamlPath === normalizedRoot) {
      return "—";
    }
    if (yamlPath.startsWith(`${normalizedRoot}/`)) {
      return yamlPath.slice(normalizedRoot.length + 1);
    }
  }
  const marker = "/yamls/";
  const index = yamlPath.indexOf(marker);
  if (index >= 0) {
    return yamlPath.slice(index + marker.length);
  }
  return yamlPath;
}

export default function JobExecutionPanel({ yamlName, pipelineNames, yamlIsValid, yamlError, onYamlSelect, onStatus }: Props) {
  const [tree, setTree] = useState<YamlTreeNode[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [selectedPath, setSelectedPath] = useState("");
  const [pipelineName, setPipelineName] = useState("");
  const [outputDir, setOutputDir] = useState("./outputs/run-001");
  const [scheduledAt, setScheduledAt] = useState("");
  const [inputOverrides, setInputOverrides] = useState("");
  const [expandedLogJobId, setExpandedLogJobId] = useState<string | null>(null);
  const [jobLogs, setJobLogs] = useState<Record<string, string>>({});
  const [loadingLogJobId, setLoadingLogJobId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const rowsPerPage = 20;

  useEffect(() => {
    if (!pipelineName && pipelineNames.length) setPipelineName(pipelineNames[0]);
  }, [pipelineNames, pipelineName]);

  useEffect(() => {
    setSelectedPath(yamlName);
  }, [yamlName]);

  async function refreshTree() {
    setTree(await getPipelineYamlTree());
  }

  async function refreshRuntime() {
    setRuntimeInfo(await getRuntimeInfo());
  }

  async function refreshJobs() {
    setJobs(await listJobs());
  }

  async function refreshAll() {
    await Promise.all([refreshTree(), refreshRuntime(), refreshJobs()]);
  }

  useEffect(() => {
    refreshAll().catch((cause: Error) => {
      setError(cause.message);
      onStatus(cause.message);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      refreshJobs().catch(() => {
        // Keep the table responsive even if a background refresh fails once.
      });
    }, 3000);

    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(jobs.length / rowsPerPage));
    setCurrentPage((page) => Math.min(page, totalPages));
    if (expandedLogJobId && !jobs.some((job) => job.id === expandedLogJobId)) {
      setExpandedLogJobId(null);
    }
  }, [jobs, expandedLogJobId]);

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
    onStatus(`Submitted job ${job.id}`);
    await refreshJobs();
  }

  async function runDue() {
    const completed = await runDueJobs(1);
    onStatus(`Ran ${completed.length} due job${completed.length === 1 ? "" : "s"}`);
    await refreshJobs();
  }

  async function cancel(jobId: string) {
    try {
      await cancelJob(jobId);
      onStatus(`Cancelled ${jobId}`);
    } finally {
      await refreshJobs();
    }
  }

  async function remove(jobId: string) {
    if (!window.confirm(`Delete job ${jobId}? This removes the job record and its log.`)) {
      return;
    }
    await deleteJob(jobId);
    setExpandedLogJobId((current) => (current === jobId ? null : current));
    setJobLogs((current) => {
      const next = { ...current };
      delete next[jobId];
      return next;
    });
    onStatus(`Deleted ${jobId}`);
    await refreshJobs();
  }

  async function rewind(jobId: string) {
    const job = await rewindJob(jobId);
    onStatus(`Rewound ${jobId} as ${job.id}`);
    setCurrentPage(1);
    await refreshJobs();
  }

  async function loadLogs(jobId: string) {
    if (expandedLogJobId === jobId) {
      setExpandedLogJobId(null);
      return;
    }
    setLoadingLogJobId(jobId);
    try {
      const response = await getJobLogs(jobId);
      setJobLogs((current) => ({
        ...current,
        [jobId]: response.log || "No logs yet.",
      }));
      setExpandedLogJobId(jobId);
    } finally {
      setLoadingLogJobId(null);
    }
  }

  const totalPages = Math.max(1, Math.ceil(jobs.length / rowsPerPage));
  const pagedJobs = useMemo(() => {
    const start = (currentPage - 1) * rowsPerPage;
    return jobs.slice(start, start + rowsPerPage);
  }, [jobs, currentPage]);

  function previousPage() {
    setCurrentPage((page) => Math.max(1, page - 1));
  }

  function nextPage() {
    setCurrentPage((page) => Math.min(totalPages, page + 1));
  }

  const canSubmit = Boolean(yamlName && yamlIsValid && pipelineNames.length);

  return (
    <section className="bg-white p-4">
      <div className="grid gap-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">Job Execution</h2>
            <p className="mt-1 text-xs text-slate-500">Select a YAML from the tree, then submit, schedule, run, cancel, and inspect logs.</p>
          </div>
          <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={() => refreshAll().catch((cause: Error) => setError(cause.message))}>
            Refresh
          </button>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <div className="grid self-start gap-3">
            <YamlTreeView
              nodes={tree}
              selectedPath={selectedPath}
              onSelect={(node) => selectNode(node).catch((cause: Error) => setError(cause.message))}
              onNavigatePath={(path) => navigatePath(path).catch((cause: Error) => setError(cause.message))}
            />
          </div>

          <div className="grid gap-4">
            <div className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-slate-950">Pipeline Controls</h3>
                <p className="mt-1 text-xs text-slate-500">Submit a job or trigger due jobs from here.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40" onClick={() => submit().catch((cause: Error) => setError(cause.message))} disabled={!canSubmit}>
                  Submit Job
                </button>
                <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={() => runDue().catch((cause: Error) => setError(cause.message))}>
                  Run Due
                </button>
              </div>
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
        </div>

        <div className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-950">Jobs</h3>
                <p className="mt-1 text-xs text-slate-500">Showing {jobs.length === 0 ? 0 : (currentPage - 1) * rowsPerPage + 1}-{Math.min(currentPage * rowsPerPage, jobs.length)} of {jobs.length}</p>
              </div>
              <div className="flex items-center gap-2 text-xs font-semibold text-slate-600">
                <button
                  className="rounded-md border border-slate-300 px-3 py-2 disabled:opacity-40"
                  onClick={previousPage}
                  disabled={currentPage <= 1}
                >
                  Previous
                </button>
                <span className="rounded-md bg-white px-3 py-2 border border-slate-200">
                  Page {currentPage} / {totalPages}
                </span>
                <button
                  className="rounded-md border border-slate-300 px-3 py-2 disabled:opacity-40"
                  onClick={nextPage}
                  disabled={currentPage >= totalPages}
                >
                  Next
                </button>
              </div>
            </div>

            <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
              <div className="overflow-x-auto">
                <table className="min-w-full table-fixed border-collapse text-left text-sm">
                  <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="w-[12%] px-3 py-2">Actions</th>
                      <th className="w-[22%] px-3 py-2">YAML Path</th>
                      <th className="w-[18%] px-3 py-2">Pipeline</th>
                      <th className="w-[11%] px-3 py-2">Status</th>
                      <th className="w-[17%] px-3 py-2">Created</th>
                      <th className="w-[20%] px-3 py-2">Last Refreshed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedJobs.length === 0 ? (
                      <tr>
                        <td className="px-3 py-4 text-sm text-slate-500" colSpan={6}>
                          No jobs yet.
                        </td>
                      </tr>
                    ) : null}
                    {pagedJobs.map((job) => {
                      const expanded = expandedLogJobId === job.id;
                      const logText = jobLogs[job.id] ?? "";
                      return (
                        <Fragment key={job.id}>
                          <tr key={job.id} className="border-t border-slate-200 align-top">
                            <td className="px-3 py-3">
                              <div className="flex flex-nowrap items-center gap-1.5 whitespace-nowrap">
                                <button
                                  className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold leading-none"
                                  title={expanded ? "Hide log" : "Show log"}
                                  onClick={() => loadLogs(job.id).catch((cause: Error) => setError(cause.message))}
                                >
                                  {loadingLogJobId === job.id ? "…" : expanded ? "◎" : "◉"}
                                </button>
                                <button
                                  className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold leading-none"
                                  title="Rewind job"
                                  onClick={() => rewind(job.id).catch((cause: Error) => setError(cause.message))}
                                >
                                  ↻
                                </button>
                                <button
                                  className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold leading-none text-red-700"
                                  title="Delete job record"
                                  onClick={() => remove(job.id).catch((cause: Error) => setError(cause.message))}
                                >
                                  -
                                </button>
                                {job.status === "queued" || job.status === "running" ? (
                                  <button
                                    className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold leading-none text-red-700"
                                    onClick={() => cancel(job.id).catch((cause: Error) => setError(cause.message))}
                                  >
                                    Cancel
                                  </button>
                                ) : null}
                              </div>
                            </td>
                            <td className="px-3 py-3 text-xs text-slate-600">
                              {formatRelativeYamlPath(job.yaml_path, runtimeInfo?.yaml_root ?? null)}
                            </td>
                            <td className="px-3 py-3 font-semibold text-slate-950">{job.pipeline_name}</td>
                            <td className="px-3 py-3">
                              <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">
                                {job.status}
                              </span>
                            </td>
                            <td className="px-3 py-3 text-xs text-slate-500">{job.created_at}</td>
                            <td className="px-3 py-3 text-xs text-slate-500">
                              {formatRelativeTime(job.updated_at)}
                            </td>
                          </tr>
                          {expanded ? (
                            <tr key={`${job.id}-log`} className="border-b border-slate-200">
                              <td className="px-3 pb-3 text-left" colSpan={6}>
                                <div className="w-full max-w-4xl rounded-md bg-black p-3 text-xs leading-6 text-emerald-300">
                                  <div className="grid gap-1 text-slate-100">
                                    <div className="font-semibold">Log for {job.id}</div>
                                    <div className="text-slate-300">YAML: {formatRelativeYamlPath(job.yaml_path, runtimeInfo?.yaml_root ?? null)}</div>
                                  </div>
                                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words">
                                    {logText || "No logs yet."}
                                  </pre>
                                </div>
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
      </div>
    </section>
  );
}