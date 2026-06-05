"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { getPipelineTemplate, getPipelineYaml, getRuntimeInfo, listPipelineTemplates, listPipelineYamls, savePipelineYaml } from "@/lib/api";
import type { PipelineTemplateSummary, RuntimeInfo, YamlSummary } from "@/types";

interface Props {
  yamlName: string;
  yamlContent: string;
  onYamlNameChange: (name: string) => void;
  onYamlContentChange: (content: string) => void;
  onPipelinesChange: (pipelines: string[]) => void;
  onStatus: (message: string) => void;
}

export default function YamlStoragePanel({
  yamlName,
  yamlContent,
  onYamlNameChange,
  onYamlContentChange,
  onPipelinesChange,
  onStatus,
}: Props) {
  const router = useRouter();
  const [yamls, setYamls] = useState<YamlSummary[]>([]);
  const [templates, setTemplates] = useState<PipelineTemplateSummary[]>([]);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState("empty");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function refresh() {
    const [runtime, yamlList, templateList] = await Promise.all([
      getRuntimeInfo(),
      listPipelineYamls(),
      listPipelineTemplates(),
    ]);
    setRuntimeInfo(runtime);
    setYamls(yamlList);
    setTemplates(templateList);
    if (templateList.length && !templateList.some((template) => template.name === selectedTemplate)) {
      setSelectedTemplate(templateList[0].name);
    }
  }

  // Run an async action with shared error/status handling so failures are visible.
  function run(label: string, fn: () => Promise<void>) {
    setError(null);
    setNotice(null);
    fn().catch((cause: Error) => {
      setError(cause.message);
      onStatus(`${label} failed: ${cause.message}`);
    });
  }

  useEffect(() => {
    run("Load storage", refresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadYaml(name: string) {
    const document = await getPipelineYaml(name);
    onYamlNameChange(document.name);
    onYamlContentChange(document.content);
    onPipelinesChange(document.pipelines);
    onStatus(document.is_valid ? `Loaded ${document.name}` : `Loaded ${document.name}; not a runnable pipeline YAML`);
  }

  async function saveYaml() {
    if (!yamlContent.trim()) {
      throw new Error("Nothing to save — create a new pipeline or load one first");
    }
    const document = await savePipelineYaml(yamlName, yamlContent, true);
    onPipelinesChange(document.pipelines);
    await refresh();
    onStatus(`Saved ${document.name}`);
    setNotice(`Saved ${document.name} to the YAML store.`);
  }

  // Seed a template into the shared editor and jump to the builder to edit it.
  async function createAndEdit() {
    const template = await getPipelineTemplate(selectedTemplate);
    onYamlContentChange(template.content);
    onStatus(`New pipeline from "${template.name}" — editing in builder`);
    router.push("/validation");
  }

  const previewLines = yamlContent ? yamlContent.split("\n").length : 0;

  return (
    <section className="border-b border-slate-200 bg-white p-4 lg:border-b-0 lg:border-r">
      <div className="grid gap-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">YAML Storage</h2>
          <p className="mt-1 text-xs text-slate-500">
            Files loaded from{" "}
            <span className="font-mono">
              {runtimeInfo?.yaml_root ?? ".bio_pipeline/yamls"}
            </span>.
          </p>
        </div>

        <div className="grid gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
          <h3 className="text-sm font-semibold text-slate-950">Create new</h3>
          <label className="grid gap-1 text-xs font-semibold text-slate-500">
            File name
            <input
              className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
              value={yamlName}
              onChange={(event) => onYamlNameChange(event.target.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-slate-500">
            Start from template
            <select
              className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
              value={selectedTemplate}
              onChange={(event) => setSelectedTemplate(event.target.value)}
            >
              {templates.map((template) => (
                <option key={template.name} value={template.name}>
                  {template.name}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white"
              onClick={() => run("Create", createAndEdit)}
            >
              Create &amp; edit
            </button>
            <button
              className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-40"
              onClick={() => run("Save", saveYaml)}
              disabled={!yamlContent.trim()}
              title={yamlContent.trim() ? "Write the current draft to the YAML store" : "Nothing to save yet"}
            >
              Save to store
            </button>
          </div>
          <p className="text-[11px] text-slate-500">
            <strong>Create &amp; edit</strong> opens the template in the builder. <strong>Save to store</strong> writes
            the current draft to <span className="font-mono">{runtimeInfo?.yaml_root ?? ".bio_pipeline/yamls"}</span> as{" "}
            <span className="font-mono">{yamlName}</span>.
          </p>
          {notice ? (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-xs font-semibold text-emerald-700">
              {notice}
            </div>
          ) : null}
          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">{error}</div>
          ) : null}
        </div>

        <div className="grid gap-1">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500">
            <span>Current draft</span>
            <span className="font-mono">{previewLines ? `${previewLines} lines` : "empty"}</span>
          </div>
          {yamlContent ? (
            <pre className="max-h-44 overflow-auto rounded-md border border-slate-200 bg-slate-950 p-3 text-xs leading-5 text-slate-100">
              {yamlContent}
            </pre>
          ) : (
            <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-3 text-xs text-slate-500">
              Nothing loaded. Create a new pipeline above, or pick a file below.
            </div>
          )}
        </div>

        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
            <span>
              {yamls.length} YAML file{yamls.length === 1 ? "" : "s"} found
            </span>
            <span>{yamls.filter((document) => document.is_valid).length} runnable</span>
          </div>
          {runtimeInfo ? (
            <div className="grid gap-1 rounded-md border border-slate-200 bg-white p-2 text-xs text-slate-500">
              <div>
                Backend reports {runtimeInfo.yaml_count} file{runtimeInfo.yaml_count === 1 ? "" : "s"} in this folder.
              </div>
              <div>
                Backend cwd: <span className="font-mono">{runtimeInfo.cwd}</span>
              </div>
              <div>
                Pipeline home: <span className="font-mono">{runtimeInfo.pipeline_home}</span>
              </div>
              {runtimeInfo.env_pipeline_home ? (
                <div>
                  PIPELINE_HOME env: <span className="font-mono">{runtimeInfo.env_pipeline_home}</span>
                </div>
              ) : null}
              {runtimeInfo.yaml_files.length ? (
                <div>
                  Files: <span className="font-mono">{runtimeInfo.yaml_files.join(", ")}</span>
                </div>
              ) : null}
            </div>
          ) : null}
          {!error && yamls.length === 0 ? (
            <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
              No YAML files found. Add files to <span className="font-mono">.bio_pipeline/yamls</span> or save one here.
            </div>
          ) : null}
          {yamls.map((document) => (
            <button
              key={document.name}
              className={`grid gap-1 rounded-md border p-3 text-left ${
                document.is_valid
                  ? "border-slate-200 bg-slate-50"
                  : "border-amber-200 bg-amber-50"
              }`}
              onClick={() => run("Load", () => loadYaml(document.name))}
            >
              <span className="text-sm font-semibold text-slate-950">{document.name}</span>
              <span className="text-xs text-slate-500">
                {document.is_valid ? document.pipelines.join(", ") || "No pipelines" : "Not a runnable pipeline YAML"}
              </span>
              {document.error ? <span className="text-xs text-amber-700">{document.error}</span> : null}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
