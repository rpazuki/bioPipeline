"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import {
  cancelMyPublishedRun,
  deleteMyPublishedRun,
  getMyPublishedRun,
  listMyPublishedRuns,
  rewindMyPublishedRun,
  runArtifactUrl,
} from "@/lib/api";
import type { PublishedRunDetail, PublishedRunSummary } from "@/types";

function statusClasses(status: string): string {
  switch (status) {
    case "succeeded":
      return "bg-emerald-100 text-emerald-800";
    case "running":
      return "bg-cyan-100 text-cyan-800";
    case "failed":
    case "partially_failed":
      return "bg-rose-100 text-rose-800";
    case "blocked":
    case "cancelled":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

export default function MyRunsPage() {
  const [runs, setRuns] = useState<PublishedRunSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, PublishedRunDetail>>({});
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
  const [openTaskLogs, setOpenTaskLogs] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Ready");

  async function refresh() {
    const next = await listMyPublishedRuns();
    setRuns(next);
    if (expandedRunId && next.some((run) => run.id === expandedRunId)) {
      const detail = await getMyPublishedRun(expandedRunId);
      setDetails((current) => ({ ...current, [expandedRunId]: detail }));
    }
  }

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
    const timer = window.setInterval(() => {
      refresh().catch(() => {});
    }, 4000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedRunId]);

  async function toggleExpand(runId: string) {
    if (expandedRunId === runId) {
      setExpandedRunId(null);
      return;
    }
    setLoadingRunId(runId);
    try {
      const detail = await getMyPublishedRun(runId);
      setDetails((current) => ({ ...current, [runId]: detail }));
      setExpandedRunId(runId);
    } finally {
      setLoadingRunId(null);
    }
  }

  function toggleTaskLog(taskId: string) {
    setOpenTaskLogs((current) => {
      const next = new Set(current);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  }

  const allSelected = runs.length > 0 && runs.every((run) => selectedIds.has(run.id));
  const someSelected = selectedIds.size > 0;

  function toggleSelectAll() {
    setSelectedIds(allSelected ? new Set() : new Set(runs.map((run) => run.id)));
  }

  function toggleSelect(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function cancelRun(runId: string) {
    await cancelMyPublishedRun(runId);
    setStatus(`Cancelled ${runId}`);
    await refresh();
  }

  async function rewindRun(runId: string) {
    const detail = await rewindMyPublishedRun(runId);
    setStatus(`Rewound as ${detail.id}`);
    await refresh();
  }

  async function deleteRun(runId: string) {
    if (!window.confirm("Delete this run? Its tasks, logs and uploaded/result files are removed.")) return;
    await deleteMyPublishedRun(runId);
    setExpandedRunId((current) => (current === runId ? null : current));
    setSelectedIds((current) => {
      const next = new Set(current);
      next.delete(runId);
      return next;
    });
    setStatus(`Deleted ${runId}`);
    await refresh();
  }

  async function deleteSelected() {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`Delete ${selectedIds.size} run(s)? Their tasks, logs and files are removed.`)) return;
    for (const id of selectedIds) {
      await deleteMyPublishedRun(id);
    }
    setStatus(`Deleted ${selectedIds.size} run(s)`);
    setExpandedRunId((current) => (current && selectedIds.has(current) ? null : current));
    setSelectedIds(new Set());
    await refresh();
  }

  const detailFor = useMemo(() => (id: string) => details[id], [details]);

  return (
    <section className="grid gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold text-slate-950">My Runs</h2>
          <p className="text-sm text-slate-500">Track your published-job runs, open a run to see its tasks, logs and results.</p>
          <button
            className="w-fit rounded-md border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-700 disabled:opacity-40"
            disabled={!someSelected}
            onClick={() => deleteSelected().catch((cause: Error) => setError(cause.message))}
          >
            Delete selected{someSelected ? ` (${selectedIds.size})` : ""}
          </button>
        </div>
        <span className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{status}</span>
      </div>
      {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

      <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
        <table className="min-w-full border-collapse text-left text-sm">
          <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="w-[4%] px-3 py-2">
                <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} title="Select all" className="cursor-pointer" />
              </th>
              <th className="w-[16%] px-3 py-2">Actions</th>
              <th className="px-3 py-2">Job</th>
              <th className="w-[12%] px-3 py-2">Status</th>
              <th className="w-[8%] px-3 py-2">Tasks</th>
              <th className="w-[18%] px-3 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-slate-500">
                  No runs yet.
                </td>
              </tr>
            ) : null}
            {runs.map((run) => {
              const expanded = expandedRunId === run.id;
              const detail = detailFor(run.id);
              const active = run.status === "queued" || run.status === "running";
              return (
                <Fragment key={run.id}>
                  <tr className="border-t border-slate-200 align-top">
                    <td className="px-3 py-3">
                      <input type="checkbox" checked={selectedIds.has(run.id)} onChange={() => toggleSelect(run.id)} className="cursor-pointer" />
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-nowrap items-center gap-1.5 whitespace-nowrap">
                        <button
                          className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold leading-none"
                          title={expanded ? "Hide tasks" : "Show tasks"}
                          onClick={() => toggleExpand(run.id).catch((cause: Error) => setError(cause.message))}
                        >
                          {loadingRunId === run.id ? "…" : expanded ? "▾" : "▸"}
                        </button>
                        {active ? (
                          <button
                            className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold leading-none text-red-700"
                            onClick={() => cancelRun(run.id).catch((cause: Error) => setError(cause.message))}
                          >
                            Cancel
                          </button>
                        ) : null}
                        {run.workspace_id ? null : (
                          <button
                            className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold leading-none"
                            title="Rewind run"
                            onClick={() => rewindRun(run.id).catch((cause: Error) => setError(cause.message))}
                          >
                            ↻
                          </button>
                        )}
                        <button
                          className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold leading-none text-red-700"
                          title="Delete run"
                          onClick={() => deleteRun(run.id).catch((cause: Error) => setError(cause.message))}
                        >
                          -
                        </button>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <button type="button" className="font-semibold text-slate-950 hover:underline" onClick={() => toggleExpand(run.id).catch((cause: Error) => setError(cause.message))}>
                        {run.published_job_name}
                      </button>
                      <div className="text-xs text-slate-500">{run.id}</div>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClasses(run.status)}`}>{run.status}</span>
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-600">{run.total}</td>
                    <td className="px-3 py-3 text-xs text-slate-500">{run.created_at}</td>
                  </tr>
                  {expanded && detail ? (
                    <tr className="border-b border-slate-200 bg-slate-50">
                      <td colSpan={6} className="px-4 pb-4 pt-2">
                        <div className="grid gap-3">
                          {detail.artifact_available ? (
                            <a href={runArtifactUrl(run.id)} download className="w-fit rounded-md bg-emerald-700 px-3 py-2 text-xs font-semibold text-white">
                              Download results
                            </a>
                          ) : (
                            <span className="text-xs text-slate-500">Results will be available to download here once the run completes.</span>
                          )}
                          <div className="grid gap-2">
                            {detail.group.tasks.map((task) => {
                              const logOpen = openTaskLogs.has(task.id);
                              return (
                                <div key={task.id} className="w-full rounded-md border border-slate-200 bg-white p-2 text-xs">
                                  <div className="flex items-center gap-2">
                                    <button
                                      className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold leading-none"
                                      title={logOpen ? "Hide log" : "Show log"}
                                      onClick={() => toggleTaskLog(task.id)}
                                    >
                                      {logOpen ? "◎" : "◉"}
                                    </button>
                                    <span className="font-semibold text-slate-900">{task.stage || task.pipeline_name}</span>
                                    <span className={`rounded-full px-2 py-0.5 font-semibold ${statusClasses(task.status)}`}>{task.status}</span>
                                  </div>
                                  {task.error ? <p className="mt-1 text-rose-700">{task.error}</p> : null}
                                  {logOpen ? (
                                    <pre className="mt-2 w-full max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-black p-2 font-mono text-[11px] leading-5 text-emerald-300">
                                      {detail.logs?.[task.id]?.trim() || "No logs yet."}
                                    </pre>
                                  ) : null}
                                </div>
                              );
                            })}
                          </div>
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
    </section>
  );
}
