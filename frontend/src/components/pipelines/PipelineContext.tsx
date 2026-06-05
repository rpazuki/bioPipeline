"use client";

import { createContext, useContext, useState } from "react";

interface PipelineState {
  yamlName: string;
  yamlContent: string;
  pipelineNames: string[];
  status: string;
  setYamlName: (name: string) => void;
  setYamlContent: (content: string) => void;
  setPipelineNames: (pipelines: string[]) => void;
  setStatus: (message: string) => void;
}

const PipelineContext = createContext<PipelineState | null>(null);

export function PipelineProvider({ children }: { children: React.ReactNode }) {
  const [yamlName, setYamlName] = useState("pipeline.yaml");
  const [yamlContent, setYamlContent] = useState("");
  const [pipelineNames, setPipelineNames] = useState<string[]>([]);
  const [status, setStatus] = useState("Ready");

  return (
    <PipelineContext.Provider
      value={{
        yamlName,
        yamlContent,
        pipelineNames,
        status,
        setYamlName,
        setYamlContent,
        setPipelineNames,
        setStatus,
      }}
    >
      {children}
    </PipelineContext.Provider>
  );
}

export function usePipeline() {
  const context = useContext(PipelineContext);
  if (!context) {
    throw new Error("usePipeline must be used within a PipelineProvider");
  }
  return context;
}
