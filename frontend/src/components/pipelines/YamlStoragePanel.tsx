"use client";

import { useEffect, useState } from "react";

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
  const [yamls, setYamls] = useState<YamlSummary[]>([]);
  const [templates, setTemplates] = useState<PipelineTemplateSummary[]>([]);
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState("empty");
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setError(null);
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

  useEffect(() => {
    refresh().catch((error: Error) => {
      setError(error.message);
      onStatus(error.message);
    });
  }, []);

  async function loadYaml(name: string) {
    const document = await getPipelineYaml(name);
    onYamlNameChange(document.name);
    onYamlContentChange(document.content);
    onPipelinesChange(document.pipelines);
    onStatus(document.is_valid ? `Loaded ${document.name}` : `Loaded ${document.name}; not a runnable pipeline YAML`);
  }

  async function saveYaml() {
    const document = await savePipelineYaml(yamlName, yamlContent, true);
    onPipelinesChange(document.pipelines);
    await refresh();
    onStatus(`Saved ${document.name}`);
  }

  async function loadTemplate() {
    const template = await getPipelineTemplate(selectedTemplate);
    onYamlContentChange(template.content);
    onStatus(`Loaded template ${template.name}`);
  }

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
        <label className="grid gap-1 text-xs font-semibold text-slate-500">
          YAML name
          <input
            className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
            value={yamlName}
            onChange={(event) => onYamlNameChange(event.target.value)}
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <button className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white" onClick={saveYaml}>
            Save YAML
          </button>
          <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={refresh}>
            Refresh
          </button>
        </div>
        <label className="grid gap-1 text-xs font-semibold text-slate-500">
          Template
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
        <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={loadTemplate}>
          Load Template
        </button>
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
          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              {error}
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
              onClick={() => loadYaml(document.name)}
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
