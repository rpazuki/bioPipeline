"use client";

import yaml from "js-yaml";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import JobStageGraph from "@/components/pipelines/JobStageGraph";
import ResizableSplitPane from "@/components/pipelines/ResizableSplitPane";
import { usePipeline } from "@/components/pipelines/PipelineContext";
import {
  getJobDefinition,
  getJobDefinitionTemplate,
  listJobDefinitions,
  listJobDefinitionTemplates,
  listPipelineYamls,
  previewJobDefinition,
  runDueJobs,
  saveDefinition,
  submitJobDefinition,
} from "@/lib/api";
import type {
  JobDefinitionPreview,
  JobDefinitionTemplateSummary,
  JobGroupDetail,
  JobGroupSummary,
  YamlSummary,
} from "@/types";

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sanitizeStageName(value: string): string {
  return value
    .trim()
    .replace(/[^A-Za-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
}

function stageNamesFromContent(text: string): string[] {
  try {
    const data = yaml.load(text);
    if (!isRecord(data) || !Array.isArray(data.stages)) return [];
    return data.stages
      .map((stage) => (isRecord(stage) && typeof stage.name === "string" ? stage.name : ""))
      .filter(Boolean);
  } catch {
    return [];
  }
}

function appendStageToDefinition(
  text: string,
  stage: {
    name: string;
    pipeline_yaml: string;
    pipeline: string;
    needs: string[];
    output_dir: string;
  },
): string {
  const data = yaml.load(text);
  if (!isRecord(data)) {
    throw new Error("Job Definition YAML must be a mapping before a stage can be added");
  }
  const stages = Array.isArray(data.stages) ? data.stages : [];
  if (stages.some((item) => isRecord(item) && item.name === stage.name)) {
    throw new Error(`Stage already exists: ${stage.name}`);
  }
  data.stages = [
    ...stages,
    {
      name: stage.name,
      ...(stage.needs.length ? { needs: stage.needs } : {}),
      pipeline_yaml: stage.pipeline_yaml,
      pipeline: stage.pipeline,
      fanout: { type: "none" },
      output_dir: stage.output_dir,
    },
  ];
  return yaml.dump(data, { indent: 2, lineWidth: -1, sortKeys: false, noRefs: true });
}

export default function JobDefinitionPanel() {
  const router = useRouter();
  const {
    jobDefinitionDraft,
    jobDefinitionName,
    jobDefinitionContent,
    setJobDefinitionDraft,
    setJobDefinitionName,
    setJobDefinitionContent,
    setStatus,
  } = usePipeline();
  const content = jobDefinitionContent || EXAMPLE;
  const editingDefinitionName = jobDefinitionName;
  const setContent = setJobDefinitionContent;

  // Load a definition handed off from the Job Storage page, then clear it.
  useEffect(() => {
    if (jobDefinitionDraft != null) {
      setContent(jobDefinitionDraft.content);
      setJobDefinitionName(jobDefinitionDraft.name);
      setJobDefinitionDraft(null);
    }
  }, [jobDefinitionDraft, setContent, setJobDefinitionDraft, setJobDefinitionName]);
  const [templates, setTemplates] = useState<JobDefinitionTemplateSummary[]>([]);
  const [pipelineYamls, setPipelineYamls] = useState<YamlSummary[]>([]);
  const [preview, setPreview] = useState<JobDefinitionPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [groups, setGroups] = useState<JobGroupSummary[]>([]);
  const [selected, setSelected] = useState<JobGroupDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stageYamlName, setStageYamlName] = useState("");
  const [stagePipelineName, setStagePipelineName] = useState("");
  const [stageName, setStageName] = useState("");
  const [stageOutputDir, setStageOutputDir] = useState("./outputs/{stage}");
  const [stageNeeds, setStageNeeds] = useState<string[]>([]);

  const existingStageNames = useMemo(() => stageNamesFromContent(content), [content]);
  const selectedPipelineYaml = useMemo(
    () => pipelineYamls.find((item) => item.name === stageYamlName) ?? null,
    [pipelineYamls, stageYamlName],
  );

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

  // Load the list of starter templates once.
  useEffect(() => {
    listJobDefinitionTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  useEffect(() => {
    listPipelineYamls()
      .then((items) => {
        const validItems = items.filter((item) => item.is_valid && item.pipelines.length > 0);
        setPipelineYamls(validItems);
        if (!stageYamlName && validItems.length) {
          setStageYamlName(validItems[0].name);
          setStagePipelineName(validItems[0].pipelines[0] ?? "");
        }
      })
      .catch(() => setPipelineYamls([]));
  }, [stageYamlName]);

  useEffect(() => {
    if (!selectedPipelineYaml) return;
    if (!selectedPipelineYaml.pipelines.includes(stagePipelineName)) {
      setStagePipelineName(selectedPipelineYaml.pipelines[0] ?? "");
    }
  }, [selectedPipelineYaml, stagePipelineName]);

  const onSelectTemplate = useCallback(
    async (name: string) => {
      if (!name) return;
      try {
        const template = await getJobDefinitionTemplate(name);
        setContent(template.content);
        setJobDefinitionName(null);
        setSelected(null);
        setStatus(`Loaded "${name}" job definition template`);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [setContent, setJobDefinitionName, setStatus],
  );

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

  const saveToName = (name: string) =>
    run(async () => {
      await saveDefinition(name, content);
      setJobDefinitionName(name);
      setStatus(`Saved ${name} to Job Storage`);
    });

  const onSave = () => {
    if (editingDefinitionName) {
      void saveToName(editingDefinitionName);
      return;
    }
    const name = window.prompt("Save definition as (e.g. growth_full.yaml):", "");
    if (!name) return;
    void saveToName(name);
  };

  const onSaveAs = () => {
    const name = window.prompt("Save definition as (e.g. growth_full.yaml):", editingDefinitionName ?? "");
    if (!name) return;
    void saveToName(name);
  };

  const onAddStage = () =>
    run(async () => {
      const normalized = sanitizeStageName(stageName || stagePipelineName || "stage");
      if (!stageYamlName || !stagePipelineName || !normalized) {
        throw new Error("Choose a pipeline YAML, pipeline, and stage name before adding a stage");
      }
      const outputDir = (stageOutputDir || `./outputs/${normalized}`).replaceAll("{stage}", normalized);
      const next = appendStageToDefinition(content, {
        name: normalized,
        pipeline_yaml: stageYamlName,
        pipeline: stagePipelineName,
        needs: stageNeeds.filter((need) => existingStageNames.includes(need)),
        output_dir: outputDir,
      });
      setContent(next);
      setStageName("");
      setStageOutputDir("./outputs/{stage}");
      setStageNeeds([]);
      setSelected(null);
      setStatus(`Added stage ${normalized}`);
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

  const leftPane = (
    <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-900">Job Definition</h2>
          <span className="text-xs text-slate-500">
            {editingDefinitionName ? `Editing ${editingDefinitionName}` : "YAML — matrix × stages × fan-out"}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="job-def-template" className="text-xs font-semibold text-slate-600">
            Start from template
          </label>
          <select
            id="job-def-template"
            aria-label="Job definition template"
            defaultValue=""
            onChange={(event) => {
              void onSelectTemplate(event.target.value);
              event.target.value = "";
            }}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-xs text-slate-700"
          >
            <option value="" disabled>
              Choose a scenario…
            </option>
            {templates.map((template) => (
              <option key={template.name} value={template.name} title={template.description}>
                {template.name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-2 rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Add Stage From Pipeline</h3>
            <span className="text-[11px] text-slate-500">{existingStageNames.length} existing stage{existingStageNames.length === 1 ? "" : "s"}</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Pipeline YAML
              <select
                className="h-9 rounded-md border border-slate-300 px-2 text-xs text-slate-900"
                value={stageYamlName}
                onChange={(event) => setStageYamlName(event.target.value)}
              >
                {pipelineYamls.length === 0 ? <option value="">No valid pipeline YAMLs found</option> : null}
                {pipelineYamls.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Pipeline
              <select
                className="h-9 rounded-md border border-slate-300 px-2 text-xs text-slate-900"
                value={stagePipelineName}
                onChange={(event) => {
                  setStagePipelineName(event.target.value);
                  setStageName((current) => current || sanitizeStageName(event.target.value));
                }}
              >
                {(selectedPipelineYaml?.pipelines ?? []).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Stage name
              <input
                className="h-9 rounded-md border border-slate-300 px-2 text-xs text-slate-900"
                value={stageName}
                placeholder={sanitizeStageName(stagePipelineName || "stage")}
                onChange={(event) => setStageName(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-slate-600">
              Output directory
              <input
                className="h-9 rounded-md border border-slate-300 px-2 text-xs text-slate-900"
                value={stageOutputDir}
                onChange={(event) => setStageOutputDir(event.target.value)}
              />
            </label>
          </div>
          {existingStageNames.length ? (
            <div className="grid gap-1">
              <div className="text-xs font-semibold text-slate-600">Depends on</div>
              <div className="flex flex-wrap gap-2">
                {existingStageNames.map((name) => (
                  <label key={name} className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700">
                    <input
                      type="checkbox"
                      checked={stageNeeds.includes(name)}
                      onChange={(event) =>
                        setStageNeeds((current) =>
                          event.target.checked ? [...current, name] : current.filter((item) => item !== name),
                        )
                      }
                    />
                    {name}
                  </label>
                ))}
              </div>
            </div>
          ) : null}
          <button
            type="button"
            onClick={onAddStage}
            disabled={busy || !stageYamlName || !stagePipelineName}
            className="w-fit rounded-md border border-cyan-200 bg-white px-3 py-2 text-sm font-semibold text-cyan-800 disabled:opacity-50"
          >
            Add Stage
          </button>
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
            {editingDefinitionName ? "Save Changes" : "Save"}
          </button>
          {editingDefinitionName ? (
            <button
              type="button"
              onClick={onSaveAs}
              disabled={busy}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50"
            >
              Save As
            </button>
          ) : null}
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
  );

  const rightPane = (
    <section className="grid content-start gap-3 rounded-md border border-slate-200 bg-white p-4 h-full">
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
  );

  return <ResizableSplitPane left={leftPane} right={rightPane} defaultSplit={50} className="gap-0" />;
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
