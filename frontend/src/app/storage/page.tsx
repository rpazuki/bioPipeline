"use client";

import { usePipeline } from "@/components/pipelines/PipelineContext";
import YamlStoragePanel from "@/components/pipelines/YamlStoragePanel";

export default function StoragePage() {
  const { yamlName, setYamlName, setYamlContent, setPipelineNames, setYamlIsValid, setYamlError, setStatus } = usePipeline();

  return (
    <div className="p-5">
      <YamlStoragePanel
        yamlName={yamlName}
        onYamlNameChange={setYamlName}
        onYamlContentChange={setYamlContent}
        onPipelinesChange={setPipelineNames}
        onYamlValidityChange={(isValid, error) => {
          setYamlIsValid(isValid);
          setYamlError(error);
        }}
        onStatus={setStatus}
      />
    </div>
  );
}
