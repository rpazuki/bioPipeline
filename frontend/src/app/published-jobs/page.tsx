"use client";

import { useEffect, useState } from "react";

import { getPublishedJob, listPublishedJobs, submitPublishedJobRun } from "@/lib/api";
import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
import type { PublishedField, PublishedJobPublicDetail, PublishedJobPublicSummary } from "@/types";

function defaultValue(field: PublishedField) {
  if (field.default !== undefined && field.default !== null) return field.default;
  if (field.type === "boolean") return false;
  if (field.type === "multi_enum" || field.type === "list") return [];
  if (field.type === "object" || field.type === "json") return "{}";
  return "";
}

function asInputValue(value: unknown): string {
  if (value == null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function FieldHelp({ field }: { field: PublishedField }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={`About ${field.label}`}
        className="grid h-5 w-5 place-items-center rounded-full border border-slate-300 text-xs font-bold text-slate-600 hover:bg-slate-50"
        onClick={() => setOpen((value) => !value)}
      >
        ?
      </button>
      {open ? (
        <span className="absolute left-6 top-0 z-20 grid w-72 gap-2 rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-600 shadow-lg">
          <span className="font-semibold text-slate-900">{field.label}</span>
          <span>{field.help || "This value customizes the published job before execution."}</span>
          <span className="rounded-md bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-700">
            Example: {field.example || asInputValue(field.default) || "value"}
          </span>
        </span>
      ) : null}
    </span>
  );
}

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: PublishedField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const base = "h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950";
  if (field.type === "boolean") {
    return <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} className="h-5 w-5" />;
  }
  if (field.type === "enum") {
    return (
      <select className={base} value={asInputValue(value)} onChange={(event) => {
        const option = field.options.find((item) => asInputValue(item.value) === event.target.value);
        onChange(option?.value ?? event.target.value);
      }}>
        {field.options.map((option) => (
          <option key={option.label} value={asInputValue(option.value)}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === "multi_enum") {
    const values = Array.isArray(value) ? value.map(asInputValue) : [];
    return (
      <div className="flex flex-wrap gap-2">
        {field.options.map((option) => {
          const optionValue = asInputValue(option.value);
          return (
            <label key={option.label} className="flex items-center gap-1.5 rounded-md border border-slate-200 px-2 py-1 text-xs">
              <input
                type="checkbox"
                checked={values.includes(optionValue)}
                onChange={(event) => {
                  const next = event.target.checked ? [...values, optionValue] : values.filter((item) => item !== optionValue);
                  onChange(field.options.filter((item) => next.includes(asInputValue(item.value))).map((item) => item.value));
                }}
              />
              {option.label}
            </label>
          );
        })}
      </div>
    );
  }
  if (field.type === "text" || field.type === "object" || field.type === "json" || field.type === "list") {
    return <textarea className="min-h-24 rounded-md border border-slate-300 p-3 font-mono text-xs" value={asInputValue(value)} onChange={(event) => onChange(event.target.value)} />;
  }
  const inputType = field.type === "integer" || field.type === "float" ? "number" : field.type === "datetime" ? "datetime-local" : "text";
  return <input type={inputType} className={base} value={asInputValue(value)} placeholder={field.placeholder || field.example} onChange={(event) => onChange(event.target.value)} />;
}

export default function PublishedJobsPage() {
  const [jobs, setJobs] = useState<PublishedJobPublicSummary[]>([]);
  const [selected, setSelected] = useState<PublishedJobPublicDetail | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [scheduledAt, setScheduledAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("Choose a published job");

  async function refresh() {
    setJobs(await listPublishedJobs());
  }

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
  }, []);

  async function selectJob(id: string) {
    const job = await getPublishedJob(id);
    setSelected(job);
    setValues(Object.fromEntries(job.fields.map((field) => [field.id, defaultValue(field)])));
    setStatus(`Selected ${job.name}`);
  }

  async function submit() {
    if (!selected) return;
    const run = await submitPublishedJobRun(selected.id, values, scheduledAt || null);
    setStatus(`Submitted run ${run.id}`);
  }

  return (
    <section className="p-5">
      <ResizableSplitPane
        defaultSplit={30}
        minLeft={20}
        minRight={30}
        left={
        <aside className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">Published Jobs</h2>
          <p className="mt-1 text-sm text-slate-500">Run admin-published workflows without seeing job or pipeline YAML.</p>
        </div>
        {jobs.length === 0 ? <p className="text-sm text-slate-500">No jobs have been published yet.</p> : null}
        {jobs.map((job) => (
          <button
            key={job.id}
            type="button"
            className={`rounded-md border px-3 py-2 text-left ${selected?.id === job.id ? "border-cyan-700 bg-cyan-50" : "border-slate-200 hover:bg-slate-50"}`}
            onClick={() => selectJob(job.id).catch((cause: Error) => setError(cause.message))}
          >
            <span className="block text-sm font-semibold text-slate-950">{job.name}</span>
            <span className="mt-1 block text-xs text-slate-500">{job.description || `Version ${job.version}`}</span>
          </button>
        ))}
      </aside>
        }
        right={
        <main className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-950">{selected?.name ?? "Job Form"}</h3>
            <p className="mt-1 text-xs text-slate-500">{selected?.description ?? status}</p>
          </div>
          <span className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">{status}</span>
        </div>
        {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}
        {selected ? (
          <div className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-2">
              {selected.fields.map((field) => (
                <label key={field.id} className="grid gap-1 text-xs font-semibold text-slate-600">
                  <span className="flex items-center gap-2">
                    {field.label}
                    <FieldHelp field={field} />
                  </span>
                  <FieldInput field={field} value={values[field.id]} onChange={(value) => setValues((current) => ({ ...current, [field.id]: value }))} />
                </label>
              ))}
              <label className="grid gap-1 text-xs font-semibold text-slate-600">
                <span className="flex items-center gap-2">
                  Run at
                  <FieldHelp field={{ id: "scheduled_at", label: "Run at", type: "datetime", required: false, help: "Optional time to queue the run for later execution.", example: "2026-06-07T18:30", options: [] }} />
                </span>
                <input className="h-9 rounded-md border border-slate-300 px-3 text-sm" type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} />
              </label>
            </div>
            <button type="button" className="w-fit rounded-md bg-cyan-700 px-4 py-2 text-sm font-semibold text-white" onClick={() => submit().catch((cause: Error) => setError(cause.message))}>
              Execute Job
            </button>
          </div>
        ) : (
          <p className="text-sm text-slate-500">Select a published job to fill its fields and execute it.</p>
        )}
      </main>
        }
      />
    </section>
  );
}
