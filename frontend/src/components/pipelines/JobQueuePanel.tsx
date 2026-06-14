"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

import {
  cancelJob,
  deleteJob,
  deleteRecurringJob,
  getJobLogs,
  getRuntimeInfo,
  listAdminPublishedRuns,
  listJobs,
  listRecurringJobs,
  rewindJob,
  runDueJobs,
  stopRecurringJob,
} from "@/lib/api";
import type { Job, PublishedRunSummary, RecurringJob, RuntimeInfo } from "@/types";

// Index published runs by the parent job they spawned so a queued job can be
// matched back to the researcher who launched the run.
export function indexRunsByParent(runs: PublishedRunSummary[]): Map<string, PublishedRunSummary> {
  const map = new Map<string, PublishedRunSummary>();
  for (const run of runs) {
    map.set(run.parent_job_id, run);
  }
  return map;
}

// Child tasks reference their group via parent_job_id; the group parent row
// matches on its own id. Admin-submitted jobs match nothing → no researcher.
export function researcherForJob(job: Job, runByParentId: Map<string, PublishedRunSummary>): string {
  const run = (job.parent_job_id ? runByParentId.get(job.parent_job_id) : undefined) ?? runByParentId.get(job.id);
  if (!run) {
    return "—";
  }
  return run.user_display_name || run.username || run.user_id;
}

function recurringEndsLabel(schedule: RecurringJob): string {
  if (schedule.ends_mode === "count") return `ends after ${schedule.ends_count} runs`;
  if (schedule.ends_mode === "until" && schedule.ends_at) return `until ${new Date(schedule.ends_at).toLocaleString()}`;
  return "no end";
}

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
  const [scheduleAgainJobId, setScheduleAgainJobId] = useState<string | null>(null);
  const [scheduleAgainAt, setScheduleAgainAt] = useState("");
  const [recurring, setRecurring] = useState<RecurringJob[]>([]);
  const [runs, setRuns] = useState<PublishedRunSummary[]>([]);
  const [colWidths, setColWidths] = useState<number[]>([44, 180, 110, 140, 160, 200, 165, 150]);

  function handleResizeStart(colIndex: number, e: React.MouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = colWidths[colIndex];

    function onMouseMove(ev: MouseEvent) {
      const newWidth = Math.max(44, startWidth + ev.clientX - startX);
      setColWidths((prev) => {
        const next = [...prev];
        next[colIndex] = newWidth;
        return next;
      });
    }

    function onMouseUp() {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    }

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }

  const rowsPerPage = 20;

  async function refreshJobs() {
    setJobs(await listJobs());
  }

  // Published-job runs carry the researcher who launched them; the raw job
  // records do not. Pull them alongside the jobs so the queue can attribute
  // each job to its researcher.
  async function refreshRuns() {
    setRuns(await listAdminPublishedRuns());
  }

  async function refreshAll() {
    await Promise.all([
      refreshJobs(),
      refreshRuns(),
      getRuntimeInfo().then(setRuntimeInfo),
      listRecurringJobs().then(setRecurring),
    ]);
  }

  async function stopRecurring(scheduleId: string) {
    await stopRecurringJob(scheduleId);
    onStatus(`Stopped recurring job ${scheduleId}`);
    await refreshAll();
  }

  async function removeRecurring(scheduleId: string) {
    if (!window.confirm("Delete this recurring job? Jobs it already submitted are kept.")) return;
    await deleteRecurringJob(scheduleId);
    onStatus(`Deleted recurring job ${scheduleId}`);
    await refreshAll();
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
      refreshRuns().catch(() => {
        // Researcher attribution is best-effort; a missed poll just keeps the
        // previous mapping until the next tick.
      });
    }, 3000);

    return () => window.clearInterval(timer);

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

  async function confirmScheduleAgain() {
    if (!scheduleAgainJobId) return;
    const at = scheduleAgainAt ? scheduleAgainAt : null;
    const job = await rewindJob(scheduleAgainJobId, at);
    setScheduleAgainJobId(null);
    setScheduleAgainAt("");
    onStatus(at ? `Scheduled ${scheduleAgainJobId} again as ${job.id} for ${at}` : `Re-ran ${scheduleAgainJobId} as ${job.id}`);
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

  // Index runs by the parent job they spawned so each queued job can be matched
  // back to the researcher who launched the published-job run.
  const runByParentId = useMemo(() => indexRunsByParent(runs), [runs]);

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

      {recurring.length > 0 ? (
        <div className="grid gap-2 rounded-md border border-slate-200 bg-white p-3">
          <h3 className="text-sm font-semibold text-slate-900">Recurring schedules</h3>
          <ul className="grid gap-2">
            {recurring.map((schedule) => (
              <li key={schedule.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 px-3 py-2 text-xs">
                <span className="grid gap-0.5">
                  <span className="font-semibold text-slate-900">{schedule.name}</span>
                  <span className="text-slate-500">
                    every {schedule.every_n} {schedule.unit} · {recurringEndsLabel(schedule)} · {schedule.runs_done} run(s) so far
                    {schedule.active ? ` · next ${new Date(schedule.next_run_at).toLocaleString()}` : " · stopped"}
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 font-semibold ${schedule.active ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>
                    {schedule.active ? "active" : "stopped"}
                  </span>
                  {schedule.active ? (
                    <button
                      className="rounded-md border border-amber-200 px-2 py-1 font-semibold text-amber-700"
                      onClick={() => stopRecurring(schedule.id).catch((cause: Error) => setError(cause.message))}
                    >
                      Stop
                    </button>
                  ) : null}
                  <button
                    className="rounded-md border border-red-200 px-2 py-1 font-semibold text-red-700"
                    onClick={() => removeRecurring(schedule.id).catch((cause: Error) => setError(cause.message))}
                  >
                    Delete
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-md border border-slate-200 bg-white">
        <div className="overflow-x-auto">
          <table
            className="table-fixed border-collapse text-left text-sm"
            style={{ width: colWidths.reduce((a, b) => a + b, 0) }}
          >
            <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th style={{ width: colWidths[0] }} className="relative px-3 py-2">
                  <input
                    type="checkbox"
                    checked={allPageSelected}
                    onChange={toggleSelectAll}
                    title="Select all on this page"
                    className="cursor-pointer"
                  />
                  <div role="separator" onMouseDown={(e) => handleResizeStart(0, e)} className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-slate-400/60" />
                </th>
                <th style={{ width: colWidths[1] }} className="relative px-3 py-2">
                  Actions
                  <div role="separator" onMouseDown={(e) => handleResizeStart(1, e)} className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-slate-400/60" />
                </th>
                <th style={{ width: colWidths[2] }} className="relative px-3 py-2">
                  Status
                  <div role="separator" onMouseDown={(e) => handleResizeStart(2, e)} className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-slate-400/60" />
                </th>
                <th style={{ width: colWidths[3] }} className="relative px-3 py-2">
                  Researcher
                  <div role="separator" onMouseDown={(e) => handleResizeStart(3, e)} className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-slate-400/60" />
                </th>
                <th style={{ width: colWidths[4] }} className="relative px-3 py-2">
                  Pipeline
                  <div role="separator" onMouseDown={(e) => handleResizeStart(4, e)} className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-slate-400/60" />
                </th>
                <th style={{ width: colWidths[5] }} className="relative px-3 py-2">
                  YAML Path
                  <div role="separator" onMouseDown={(e) => handleResizeStart(5, e)} className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-slate-400/60" />
                </th>
                <th style={{ width: colWidths[6] }} className="relative px-3 py-2">
                  Created
                  <div role="separator" onMouseDown={(e) => handleResizeStart(6, e)} className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-slate-400/60" />
                </th>
                <th style={{ width: colWidths[7] }} className="relative px-3 py-2">
                  Last Refreshed
                  <div role="separator" onMouseDown={(e) => handleResizeStart(7, e)} className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-slate-400/60" />
                </th>
              </tr>
            </thead>
            <tbody>
              {pagedJobs.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-sm text-slate-500" colSpan={8}>
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
                            title="Rewind job (run again now)"
                            onClick={() => rewind(job.id).catch((cause: Error) => setError(cause.message))}
                          >
                            ↻
                          </button>
                          <button
                            className="rounded-md border border-slate-300 px-2 py-1 text-xs font-semibold leading-none"
                            title="Schedule again (run at a chosen time)"
                            onClick={() => { setScheduleAgainJobId(job.id); setScheduleAgainAt(""); }}
                          >
                            🗓
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
                      <td className="px-3 py-3">
                        <span className={`rounded-full px-2 py-1 text-xs font-semibold ${statusClasses(job.status)}`}>
                          {job.status}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-600">{researcherForJob(job, runByParentId)}</td>
                      <td className="px-3 py-3 font-semibold text-slate-950">{job.pipeline_name}</td>
                      <td className="px-3 py-3 text-xs text-slate-600">
                        {formatRelativeYamlPath(job.yaml_path, runtimeInfo?.yaml_root ?? null)}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-500">{job.created_at}</td>
                      <td className="px-3 py-3 text-xs text-slate-500">{formatRelativeTime(job.updated_at)}</td>
                    </tr>
                    {expanded ? (
                      <tr key={`${job.id}-log`} className="border-b border-slate-200">
                        <td className="px-3 pb-3 text-left" colSpan={8}>
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

      {scheduleAgainJobId ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4" onClick={() => setScheduleAgainJobId(null)}>
          <div className="grid w-full max-w-sm gap-3 rounded-md border border-slate-200 bg-white p-4" onClick={(event) => event.stopPropagation()}>
            <h4 className="text-sm font-semibold text-slate-900">Schedule this job again</h4>
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Run at (leave blank to run now)
              <input
                type="datetime-local"
                value={scheduleAgainAt}
                onChange={(event) => setScheduleAgainAt(event.target.value)}
                className="h-9 rounded-md border border-slate-300 px-3 text-sm font-normal text-slate-900"
              />
            </label>
            <div className="flex gap-2">
              <button
                className="rounded-md bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white"
                onClick={() => confirmScheduleAgain().catch((cause: Error) => setError(cause.message))}
              >
                {scheduleAgainAt ? "Schedule" : "Run now"}
              </button>
              <button
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600"
                onClick={() => setScheduleAgainJobId(null)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
