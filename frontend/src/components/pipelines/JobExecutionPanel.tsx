"use client";

import { useEffect, useState } from "react";

import { cancelJob, getJobLogs, listJobs, runDueJobs, submitJob } from "@/lib/api";
import type { Job } from "@/types";

interface Props {
  yamlName: string;
  pipelineNames: string[];
  onStatus: (message: string) => void;
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

export default function JobExecutionPanel({ yamlName, pipelineNames, onStatus }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [pipelineName, setPipelineName] = useState("");
  const [outputDir, setOutputDir] = useState("./outputs/run-001");
  const [scheduledAt, setScheduledAt] = useState("");
  const [inputOverrides, setInputOverrides] = useState("");
  const [selectedLog, setSelectedLog] = useState("");

  useEffect(() => {
    if (!pipelineName && pipelineNames.length) setPipelineName(pipelineNames[0]);
  }, [pipelineNames, pipelineName]);

  async function refreshJobs() {
    setJobs(await listJobs());
  }

  useEffect(() => {
    refreshJobs().catch((error: Error) => onStatus(error.message));
  }, []);

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
    await cancelJob(jobId);
    await refreshJobs();
    onStatus(`Cancelled ${jobId}`);
  }

  async function loadLogs(jobId: string) {
    const response = await getJobLogs(jobId);
    setSelectedLog(response.log || "No logs yet.");
  }

  return (
    <section className="bg-white p-4">
      <div className="grid gap-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">Job Execution</h2>
            <p className="mt-1 text-xs text-slate-500">Submit, schedule, run, cancel, and inspect logs.</p>
          </div>
          <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={refreshJobs}>
            Refresh
          </button>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-1 text-xs font-semibold text-slate-500">
            Pipeline
            <select
              className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
              value={pipelineName}
              onChange={(event) => setPipelineName(event.target.value)}
            >
              {pipelineNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold text-slate-500">
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
        <div className="flex flex-wrap gap-2">
          <button className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white" onClick={submit}>
            Submit Job
          </button>
          <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={runDue}>
            Run Due
          </button>
        </div>
        <div className="grid gap-2">
          {jobs.map((job) => (
            <div key={job.id} className="grid gap-2 border-t border-slate-200 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-slate-950">{job.pipeline_name}</div>
                  <div className="text-xs text-slate-500">{job.id}</div>
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">
                  {job.status}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold" onClick={() => loadLogs(job.id)}>
                  Logs
                </button>
                {job.status === "queued" || job.status === "running" ? (
                  <button className="rounded-md border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-700" onClick={() => cancel(job.id)}>
                    Cancel
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
        <pre className="min-h-44 max-h-80 overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-6 text-slate-100">
          {selectedLog}
        </pre>
      </div>
    </section>
  );
}

