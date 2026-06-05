"use client";

import { usePipeline } from "@/components/pipelines/PipelineContext";
import ValidationPanel from "@/components/pipelines/ValidationPanel";

export default function ValidationPage() {
  const { yamlContent, setYamlContent, setPipelineNames, setStatus } = usePipeline();

  return (
    <div className="grid min-h-[620px] grid-rows-[auto_1fr] p-5">
      <ValidationPanel
        yamlContent={yamlContent}
        onYamlContentChange={setYamlContent}
        onPipelinesChange={setPipelineNames}
        onStatus={setStatus}
      />
      <textarea
        className="min-h-[420px] resize-none rounded-md border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-950 outline-none"
        spellCheck={false}
        value={yamlContent}
        onChange={(event) => setYamlContent(event.target.value)}
      />
    </div>
  );
}
