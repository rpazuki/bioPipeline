"use client";

import { useEffect, useState } from "react";

import { getPipelineTemplate, getPipelineYaml, listPipelineTemplates, listPipelineYamls, savePipelineYaml } from "@/lib/api";
import type { PipelineTemplateSummary, YamlSummary } from "@/types";

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
  const [selectedTemplate, setSelectedTemplate] = useState("empty");

  async function refresh() {
    const [yamlList, templateList] = await Promise.all([
      listPipelineYamls(),
      listPipelineTemplates(),
    ]);
    setYamls(yamlList);
    setTemplates(templateList);
    if (templateList.length && !templateList.some((template) => template.name === selectedTemplate)) {
      setSelectedTemplate(templateList[0].name);
    }
  }

  useEffect(() => {
    refresh().catch((error: Error) => onStatus(error.message));
  }, []);

  async function loadYaml(name: string) {
    const document = await getPipelineYaml(name);
    onYamlNameChange(document.name);
    onYamlContentChange(document.content);
    onPipelinesChange(document.pipelines);
    onStatus(`Loaded ${document.name}`);
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
          <p className="mt-1 text-xs text-slate-500">Create, load, and persist pipeline YAML files.</p>
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
          {yamls.map((document) => (
            <button
              key={document.name}
              className="grid gap-1 rounded-md border border-slate-200 bg-slate-50 p-3 text-left"
              onClick={() => loadYaml(document.name)}
            >
              <span className="text-sm font-semibold text-slate-950">{document.name}</span>
              <span className="text-xs text-slate-500">{document.pipelines.join(", ") || "No pipelines"}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

