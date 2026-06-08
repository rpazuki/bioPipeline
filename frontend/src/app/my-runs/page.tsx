"use client";

import { useEffect, useState } from "react";

import { cancelMyPublishedRun, getMyPublishedRun, listMyPublishedRuns, rewindMyPublishedRun } from "@/lib/api";
import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
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
  const [selected, setSelected] = useState<PublishedRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Ready");

  async function refresh() {
    setRuns(await listMyPublishedRuns());
  }

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
    const timer = window.setInterval(() => {
      refresh().catch(() => {});
    }, 4000);
    return () => window.clearInterval(timer);
  }, []);

  async function openRun(runId: string) {
    setSelected(await getMyPublishedRun(runId));
  }

  async function cancelRun(runId: string) {
    const detail = await cancelMyPublishedRun(runId);
    setSelected(detail);
    setStatus(`Cancelled ${runId}`);
    await refresh();
  }

  async function rewindRun(runId: string) {
    const detail = await rewindMyPublishedRun(runId);
    setSelected(detail);
    setStatus(`Rewound as ${detail.id}`);
    await refresh();
  }

  return (
    <section className="grid gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">My Runs</h2>
          <p className="mt-1 text-sm text-slate-500">Track published job runs, cancel active work, or rewind with previous values.</p>
        </div>
        <span className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{status}</span>
      </div>
      {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}
      <ResizableSplitPane
        defaultSplit={65}
        left={
        <section className="overflow-hidden rounded-md border border-slate-200 bg-white h-full">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-100 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Job</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Tasks</th>
                <th className="px-3 py-2">Created</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-slate-500">
                    No runs yet.
                  </td>
                </tr>
              ) : null}
              {runs.map((run) => (
                <tr key={run.id} className="border-t border-slate-200">
                  <td className="px-3 py-3">
                    <button type="button" className="font-semibold text-slate-950 hover:underline" onClick={() => openRun(run.id).catch((cause: Error) => setError(cause.message))}>
                      {run.published_job_name}
                    </button>
                    <div className="text-xs text-slate-500">{run.id}</div>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClasses(run.status)}`}>{run.status}</span>
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-600">{run.total}</td>
                  <td className="px-3 py-3 text-xs text-slate-500">{run.created_at}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      <button type="button" className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold" onClick={() => rewindRun(run.id).catch((cause: Error) => setError(cause.message))}>
                        Rewind
                      </button>
                      {run.status === "queued" || run.status === "running" ? (
                        <button type="button" className="rounded-md border border-rose-200 px-2 py-1 text-xs font-semibold text-rose-700" onClick={() => cancelRun(run.id).catch((cause: Error) => setError(cause.message))}>
                          Cancel
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        }
        right={
        <aside className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
          <h3 className="text-sm font-semibold text-slate-950">Run Detail</h3>
          {selected ? (
            <div className="grid gap-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-slate-900">{selected.published_job_name}</span>
                <span className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClasses(selected.status)}`}>{selected.status}</span>
              </div>
              <div className="rounded-md bg-slate-50 p-3">
                <div className="text-xs font-semibold uppercase text-slate-500">Previous values</div>
                <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap text-xs text-slate-700">{JSON.stringify(selected.values, null, 2)}</pre>
              </div>
              <div className="grid gap-2">
                {selected.group.tasks.map((task) => (
                  <div key={task.id} className="rounded-md border border-slate-200 p-2 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-slate-900">{task.stage || task.pipeline_name}</span>
                      <span className={`rounded-full px-2 py-0.5 font-semibold ${statusClasses(task.status)}`}>{task.status}</span>
                    </div>
                    {task.error ? <p className="mt-1 text-rose-700">{task.error}</p> : null}
                    <div className="mt-2 rounded-md bg-slate-950 p-2">
                      <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">Log</div>
                      <pre className="max-h-44 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-5 text-slate-100">
                        {selected.logs?.[task.id]?.trim() || "No logs yet."}
                      </pre>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500">Open a run to inspect submitted values and task statuses.</p>
          )}
        </aside>
        }
      />
    </section>
  );
}
