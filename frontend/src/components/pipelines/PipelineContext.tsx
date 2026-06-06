"use client";

import { createContext, useContext, useState } from "react";

interface PipelineState {
  yamlName: string;
  yamlContent: string;
  pipelineNames: string[];
  yamlIsValid: boolean;
  yamlError: string | null;
  status: string;
  setYamlName: (name: string) => void;
  setYamlContent: (content: string) => void;
  setPipelineNames: (pipelines: string[]) => void;
  setYamlIsValid: (isValid: boolean) => void;
  setYamlError: (message: string | null) => void;
  setStatus: (message: string) => void;
}

const PipelineContext = createContext<PipelineState | null>(null);

export function PipelineProvider({ children }: { children: React.ReactNode }) {
  const [yamlName, setYamlName] = useState("pipeline.yaml");
  const [yamlContent, setYamlContent] = useState("");
  const [pipelineNames, setPipelineNames] = useState<string[]>([]);
  const [yamlIsValid, setYamlIsValid] = useState(true);
  const [yamlError, setYamlError] = useState<string | null>(null);
  const [status, setStatus] = useState("Ready");

  return (
    <PipelineContext.Provider
      value={{
        yamlName,
        yamlContent,
        pipelineNames,
        yamlIsValid,
        yamlError,
        status,
        setYamlName,
        setYamlContent,
        setPipelineNames,
        setYamlIsValid,
        setYamlError,
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
