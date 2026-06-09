"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import { cancelJob, deleteJob, getJobLogs, getRuntimeInfo, listJobs, rewindJob, runDueJobs } from "@/lib/api";
import type { Job, RuntimeInfo } from "@/types";

interface Props {
  onStatus: (message: string) => void;
}

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

export default function JobQueuePanel({ onStatus }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [expandedLogJobId, setExpandedLogJobId] = useState<string | null>(null);
  const [jobLogs, setJobLogs] = useState<Record<string, string>>({});
  const [loadingLogJobId, setLoadingLogJobId] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const rowsPerPage = 20;

  async function refreshJobs() {
    setJobs(await listJobs());
  }

  async function refreshAll() {
    await Promise.all([refreshJobs(), getRuntimeInfo().then(setRuntimeInfo)]);
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

  // Stream the open log: while a job's log is expanded, refresh it on an
  // interval so a running job's output appends live instead of only updating
  // when the log is closed and reopened.
  useEffect(() => {
    if (!expandedLogJobId) {
      return;
    }
    const jobId = expandedLogJobId;
    let cancelled = false;

    async function pullLog() {
      try {
        const response = await getJobLogs(jobId);
        if (!cancelled) {
          setJobLogs((current) => ({ ...current, [jobId]: response.log || "No logs yet." }));
        }
      } catch {
        // Keep the last log visible if a single refresh fails.
      }
    }

    const timer = window.setInterval(pullLog, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [expandedLogJobId]);

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

  const pagedJobIds = useMemo(() => pagedJobs.map((j) => j.id), [pagedJobs]);
  const allPageSelected = pagedJobIds.length > 0 && pagedJobIds.every((id) => selectedIds.has(id));
  const someSelected = selectedIds.size > 0;

  function toggleSelectAll() {
    if (allPageSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        pagedJobIds.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelectedIds((prev) => new Set([...prev, ...pagedJobIds]));
    }
  }

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function removeSelected() {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`Delete ${selectedIds.size} job(s)? This removes the job records and their logs.`)) return;
    for (const id of selectedIds) {
      await deleteJob(id);
      setExpandedLogJobId((cur) => (cur === id ? null : cur));
      setJobLogs((cur) => {
        const next = { ...cur };
        delete next[id];
        return next;
      });
    }
    onStatus(`Deleted ${selectedIds.size} job(s)`);
    setSelectedIds(new Set());
    await refreshJobs();
  }

  async function rewindSelected() {
    if (selectedIds.size === 0) return;
    let count = 0;
    for (const id of selectedIds) {
      await rewindJob(id);
      count++;
    }
    onStatus(`Rewound ${count} job(s)`);
    setSelectedIds(new Set());
    setCurrentPage(1);
    await refreshJobs();
  }

  function previousPage() {
    setCurrentPage((page) => Math.max(1, page - 1));
  }

  function nextPage() {
    setCurrentPage((page) => Math.min(totalPages, page + 1));
  }

  return (
    <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-950">Job Queue</h2>
          <p className="text-xs text-slate-500">
            Showing {jobs.length === 0 ? 0 : (currentPage - 1) * rowsPerPage + 1}-
            {Math.min(currentPage * rowsPerPage, jobs.length)} of {jobs.length}
          </p>
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-600">
            <button
              className="rounded-md border border-red-200 px-3 py-1.5 text-red-700 disabled:opacity-40"
              disabled={!someSelected}
              onClick={() => removeSelected().catch((cause: Error) => setError(cause.message))}
            >
              Delete{someSelected ? ` (${selectedIds.size})` : ""}
            </button>
            <button
              className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40"
              disabled={!someSelected}
              onClick={() => rewindSelected().catch((cause: Error) => setError(cause.message))}
            >
              Rewind{someSelected ? ` (${selectedIds.size})` : ""}
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-600">
          <button
            className="rounded-md bg-cyan-700 px-3 py-2 text-white"
            onClick={() => runDue().catch((cause: Error) => setError(cause.message))}
          >
            Run Due
          </button>
          <button
            className="rounded-md border border-slate-300 px-3 py-2"
            onClick={() => refreshAll().catch((cause: Error) => setError(cause.message))}
          >
            Refresh
          </button>
          <button className="rounded-md border border-slate-300 px-3 py-2 disabled:opacity-40" onClick={previousPage} disabled={currentPage <= 1}>
            Previous
          </button>
          <span className="rounded-md border border-slate-200 bg-white px-3 py-2">
            Page {currentPage} / {totalPages}
          </span>
          <button className="rounded-md border border-slate-300 px-3 py-2 disabled:opacity-40" onClick={nextPage} disabled={currentPage >= totalPages}>
            Next
          </button>
        </div>
      </div>

      {error ? <p className="text-xs text-rose-700">{error}</p> : null}

      <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
        <div className="overflow-x-auto">
          <table className="min-w-full table-fixed border-collapse text-left text-sm">
            <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="w-[4%] px-3 py-2">
                  <input
                    type="checkbox"
                    checked={allPageSelected}
                    onChange={toggleSelectAll}
                    title="Select all on this page"
                    className="cursor-pointer"
                  />
                </th>
                <th className="w-[11%] px-3 py-2">Actions</th>
                <th className="w-[21%] px-3 py-2">YAML Path</th>
                <th className="w-[17%] px-3 py-2">Pipeline</th>
                <th className="w-[10%] px-3 py-2">Status</th>
                <th className="w-[17%] px-3 py-2">Created</th>
                <th className="w-[20%] px-3 py-2">Last Refreshed</th>
              </tr>
            </thead>
            <tbody>
              {pagedJobs.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-sm text-slate-500" colSpan={7}>
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
                        <input
                          type="checkbox"
                          checked={selectedIds.has(job.id)}
                          onChange={() => toggleSelect(job.id)}
                          className="cursor-pointer"
                        />
                      </td>
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
                        <span className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClasses(job.status)}`}>
                          {job.status}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-500">{job.created_at}</td>
                      <td className="px-3 py-3 text-xs text-slate-500">{formatRelativeTime(job.updated_at)}</td>
                    </tr>
                    {expanded ? (
                      <tr key={`${job.id}-log`} className="border-b border-slate-200">
                        <td className="px-3 pb-3 text-left" colSpan={7}>
                          <div className="w-full rounded-md bg-black p-3 text-xs leading-6 text-emerald-300">
                            <div className="grid gap-1 text-slate-100">
                              <div className="font-semibold">Log for {job.id}</div>
                              <div className="text-slate-300">
                                YAML: {formatRelativeYamlPath(job.yaml_path, runtimeInfo?.yaml_root ?? null)}
                              </div>
                            </div>
                            <pre className="w-full max-h-72 overflow-auto whitespace-pre-wrap break-words">
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
    </section>
  );
}
