"use client";

import { useState } from "react";

import JobExecutionPanel from "./JobExecutionPanel";
import ValidationPanel from "./ValidationPanel";
import YamlStoragePanel from "./YamlStoragePanel";

export default function PipelineManagerClient() {
  const [yamlName, setYamlName] = useState("pipeline.yaml");
  const [yamlContent, setYamlContent] = useState("");
  const [pipelineNames, setPipelineNames] = useState<string[]>([]);
  const [status, setStatus] = useState("Ready");

  return (
    <main className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-950">Bio Pipeline Manager</h1>
            <p className="mt-1 text-sm text-slate-500">Design, validate, queue, and run labUtils YAML pipelines.</p>
          </div>
          <div className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">{status}</div>
        </div>
      </header>
      <div className="grid min-h-[calc(100vh-81px)] lg:grid-cols-[300px_minmax(420px,1fr)_420px]">
        <YamlStoragePanel
          yamlName={yamlName}
          yamlContent={yamlContent}
          onYamlNameChange={setYamlName}
          onYamlContentChange={setYamlContent}
          onPipelinesChange={setPipelineNames}
          onStatus={setStatus}
        />
        <section className="grid min-h-[620px] grid-rows-[auto_1fr] border-b border-slate-200 bg-white lg:border-b-0 lg:border-r">
          <ValidationPanel
            yamlContent={yamlContent}
            onPipelinesChange={setPipelineNames}
            onStatus={setStatus}
          />
          <textarea
            className="min-h-[420px] resize-none border-0 bg-slate-50 p-4 text-sm leading-6 text-slate-950 outline-none"
            spellCheck={false}
            value={yamlContent}
            onChange={(event) => setYamlContent(event.target.value)}
          />
        </section>
        <JobExecutionPanel yamlName={yamlName} pipelineNames={pipelineNames} onStatus={setStatus} />
      </div>
    </main>
  );
}

