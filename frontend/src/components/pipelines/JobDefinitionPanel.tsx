"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import JobStageGraph from "@/components/pipelines/JobStageGraph";
import { usePipeline } from "@/components/pipelines/PipelineContext";
import {
  getJobDefinition,
  listJobDefinitions,
  previewJobDefinition,
  runDueJobs,
  saveDefinition,
  submitJobDefinition,
} from "@/lib/api";
import type { JobDefinitionPreview, JobGroupDetail, JobGroupSummary } from "@/types";

// Previews without touching the filesystem (all fan-out is "none"). For real
// fan-out over data files, set a stage's fanout to mapping_file / patterns /
// folders — those read the referenced files when the definition is expanded.
const EXAMPLE = `job: growth_rates_demo
variables:
  run_tag: [batch-A, batch-B]
  variant:
    - {name: no_replicates, pipeline: growth_rate_fit_pipeline}
    - {name: replicates, pipeline: growth_rate_replicates_fit_pipeline}
defaults:
  data_root: "/data/{run_tag}"
stages:
  - name: preprocess
    pipeline_yaml: growth_rates_pipeline.yaml
    pipeline: "{variant.pipeline}"
    fanout: {type: none}
    output_dir: "{data_root}/processed/{variant.name}"
    input_sources:
      raw_data: "{data_root}/data/mediabot.csv"
  - name: collate
    needs: [preprocess]
    pipeline_yaml: collateing_pipeline.yaml
    pipeline: collate_per_strain_pipeline
    fanout: {type: none}
    input_sources:
      folders_list: "{data_root}/processed/{variant.name}"
    process_arg_mapping:
      saved_dataframes:
        strain_col: strain
    output_dir: "{data_root}/processed/{variant.name}_STRAINS"
`;

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

function formatMatrixKey(matrixKey: Record<string, string>): string {
  const entries = Object.entries(matrixKey);
  if (entries.length === 0) return "—";
  return entries.map(([k, v]) => `${k}=${v}`).join(", ");
}

export default function JobDefinitionPanel() {
  const router = useRouter();
  const { jobDefinitionDraft, setJobDefinitionDraft, setStatus } = usePipeline();
  const [content, setContent] = useState(EXAMPLE);

  // Load a definition handed off from the Job Storage page, then clear it.
  useEffect(() => {
    if (jobDefinitionDraft != null) {
      setContent(jobDefinitionDraft);
      setJobDefinitionDraft(null);
    }
  }, [jobDefinitionDraft, setJobDefinitionDraft]);
  const [preview, setPreview] = useState<JobDefinitionPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [groups, setGroups] = useState<JobGroupSummary[]>([]);
  const [selected, setSelected] = useState<JobGroupDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshGroups = useCallback(async () => {
    try {
      setGroups(await listJobDefinitions());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refreshGroups();
  }, [refreshGroups]);

  const runPreview = useCallback(async (text: string) => {
    try {
      const result = await previewJobDefinition(text);
      setPreview(result);
      setPreviewError(null);
    } catch (err) {
      setPreview(null);
      setPreviewError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  // Live, debounced preview: expand the definition as the user types and show
  // the plan (stage DAG + task list) or an inline validation error.
  useEffect(() => {
    setSelected(null);
    const handle = window.setTimeout(() => {
      void runPreview(content);
    }, 500);
    return () => window.clearTimeout(handle);
  }, [content, runPreview]);

  const run = useCallback(
    async (action: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      try {
        await action();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const onPreview = () => {
    setSelected(null);
    void runPreview(content);
  };

  const onSubmit = () =>
    run(async () => {
      await submitJobDefinition(content);
      router.push("/");
    });

  const onSave = () =>
    run(async () => {
      const name = window.prompt("Save definition as (e.g. growth_full.yaml):", "");
      if (!name) return;
      await saveDefinition(name, content);
      setStatus(`Saved ${name} to Job Storage`);
    });

  const onRunDue = () =>
    run(async () => {
      await runDueJobs(2);
      await refreshGroups();
      if (selected) {
        setSelected(await getJobDefinition(selected.parent_job_id));
      }
    });

  const onOpenGroup = (parentJobId: string) =>
    run(async () => {
      setPreview(null);
      setSelected(await getJobDefinition(parentJobId));
    });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Job Definition</h2>
          <span className="text-xs text-slate-500">YAML — matrix × stages × fan-out</span>
        </div>
        <textarea
          aria-label="Job Definition YAML"
          className="h-96 w-full resize-y rounded-md border border-slate-300 p-3 font-mono text-xs text-slate-900"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          spellCheck={false}
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onPreview}
            disabled={busy}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            Preview
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={busy}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            Save
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={busy}
            className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            Submit
          </button>
          <button
            type="button"
            onClick={onRunDue}
            disabled={busy}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            Run due
          </button>
        </div>
        {previewError ? (
          <p className="rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700">{previewError}</p>
        ) : (
          <p className="text-xs text-emerald-700">
            {preview ? `Valid — expands to ${preview.task_count} task${preview.task_count === 1 ? "" : "s"}.` : "Validating…"}
          </p>
        )}
        {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      </section>

      <section className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4">
        {selected ? (
          <GroupView group={selected} />
        ) : preview ? (
          <div className="grid gap-3">
            <JobStageGraph tasks={preview.tasks} />
            <PreviewView preview={preview} />
          </div>
        ) : (
          <p className="text-xs text-slate-500">Edit the definition to see its plan, or open a submitted job below.</p>
        )}

        <div className="mt-2 grid gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Submitted jobs</h3>
          {groups.length === 0 ? (
            <p className="text-xs text-slate-500">No job definitions submitted yet.</p>
          ) : (
            <ul className="grid gap-1.5">
              {groups.map((group) => (
                <li key={group.parent_job_id}>
                  <button
                    type="button"
                    onClick={() => onOpenGroup(group.parent_job_id)}
                    className="flex w-full items-center justify-between gap-2 rounded-md border border-slate-200 px-3 py-2 text-left hover:bg-slate-50"
                  >
                    <span className="font-mono text-xs text-slate-900">{group.job_name || group.parent_job_id}</span>
                    <span className="flex items-center gap-2">
                      <span className="text-xs text-slate-500">{group.total} tasks</span>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusClasses(group.status)}`}>
                        {group.status}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}

function PreviewView({ preview }: { preview: JobDefinitionPreview }) {
  return (
    <div className="grid gap-2">
      <h3 className="text-sm font-semibold text-slate-900">
        Preview — {preview.task_count} task{preview.task_count === 1 ? "" : "s"}
      </h3>
      <ul className="grid max-h-72 gap-1.5 overflow-y-auto">
        {preview.tasks.map((task, index) => (
          <li key={index} className="rounded-md border border-slate-200 px-3 py-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-slate-900">
                [{task.stage}]
                {task.deferred ? (
                  <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-500">
                    deferred · fans out at run time
                  </span>
                ) : null}
              </span>
              <span className="text-slate-500">{formatMatrixKey(task.matrix_key)}</span>
            </div>
            <div className="mt-1 text-slate-700">
              {task.pipeline_name} <span className="text-slate-400">({task.pipeline_yaml})</span>
            </div>
            <div className="font-mono text-[11px] text-slate-500">{task.output_dir}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function GroupView({ group }: { group: JobGroupDetail }) {
  const stages = Array.from(new Set(group.tasks.map((task) => task.stage ?? "")));
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{group.job_name || group.parent_job_id}</h3>
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusClasses(group.status)}`}>
          {group.status}
        </span>
      </div>
      <div className="text-xs text-slate-500">
        {Object.entries(group.counts)
          .map(([name, count]) => `${count} ${name}`)
          .join(" · ")}
      </div>
      {stages.map((stage) => (
        <div key={stage} className="grid gap-1">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{stage}</div>
          <ul className="grid gap-1">
            {group.tasks
              .filter((task) => (task.stage ?? "") === stage)
              .map((task) => (
                <li
                  key={task.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-slate-200 px-3 py-1.5 text-xs"
                >
                  <span className="text-slate-500">{formatMatrixKey(task.matrix_key ?? {})}</span>
                  <span className={`rounded-full px-2 py-0.5 font-semibold ${statusClasses(task.status)}`}>
                    {task.status}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
