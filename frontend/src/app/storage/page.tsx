"use client";

import { usePipeline } from "@/components/pipelines/PipelineContext";
import YamlStoragePanel from "@/components/pipelines/YamlStoragePanel";

export default function StoragePage() {
  const { yamlName, yamlContent, setYamlName, setYamlContent, setPipelineNames, setStatus } = usePipeline();

  return (
    <div className="p-5">
      <YamlStoragePanel
        yamlName={yamlName}
        yamlContent={yamlContent}
        onYamlNameChange={setYamlName}
        onYamlContentChange={setYamlContent}
        onPipelinesChange={setPipelineNames}
        onStatus={setStatus}
      />
    </div>
  );
}
