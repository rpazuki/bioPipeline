"use client";

import { createContext, useContext, useEffect, useState } from "react";

const SESSION_KEY = "bioPipeline.pipelineSession.v1";

interface PipelineState {
  yamlName: string;
  yamlContent: string;
  pipelineNames: string[];
  yamlIsValid: boolean;
  yamlError: string | null;
  status: string;
  /** Pending Job Definition handed off from Job Storage to the editor. */
  jobDefinitionDraft: { name: string; content: string } | null;
  jobDefinitionName: string | null;
  jobDefinitionContent: string;
  setYamlName: (name: string) => void;
  setYamlContent: (content: string) => void;
  setPipelineNames: (pipelines: string[]) => void;
  setYamlIsValid: (isValid: boolean) => void;
  setYamlError: (message: string | null) => void;
  setStatus: (message: string) => void;
  setJobDefinitionDraft: (draft: { name: string; content: string } | null) => void;
  setJobDefinitionName: (name: string | null) => void;
  setJobDefinitionContent: (content: string) => void;
}

const PipelineContext = createContext<PipelineState | null>(null);

interface PersistedPipelineState {
  yamlName?: string;
  yamlContent?: string;
  pipelineNames?: string[];
  yamlIsValid?: boolean;
  yamlError?: string | null;
  jobDefinitionName?: string | null;
  jobDefinitionContent?: string;
}

function readPersistedState(): PersistedPipelineState {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as PersistedPipelineState) : {};
  } catch {
    return {};
  }
}

export function PipelineProvider({ children }: { children: React.ReactNode }) {
  const [initial] = useState(readPersistedState);
  const [yamlName, setYamlName] = useState(initial.yamlName ?? "pipeline.yaml");
  const [yamlContent, setYamlContent] = useState(initial.yamlContent ?? "");
  const [pipelineNames, setPipelineNames] = useState<string[]>(initial.pipelineNames ?? []);
  const [yamlIsValid, setYamlIsValid] = useState(initial.yamlIsValid ?? true);
  const [yamlError, setYamlError] = useState<string | null>(initial.yamlError ?? null);
  const [status, setStatus] = useState("Ready");
  const [jobDefinitionDraft, setJobDefinitionDraft] = useState<{ name: string; content: string } | null>(null);
  const [jobDefinitionName, setJobDefinitionName] = useState<string | null>(initial.jobDefinitionName ?? null);
  const [jobDefinitionContent, setJobDefinitionContent] = useState(initial.jobDefinitionContent ?? "");

  useEffect(() => {
    const payload: PersistedPipelineState = {
      yamlName,
      yamlContent,
      pipelineNames,
      yamlIsValid,
      yamlError,
      jobDefinitionName,
      jobDefinitionContent,
    };
    try {
      window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(payload));
    } catch {
      // Ignore storage quota/privacy failures; in-memory state still works.
    }
  }, [jobDefinitionContent, jobDefinitionName, pipelineNames, yamlContent, yamlError, yamlIsValid, yamlName]);

  return (
    <PipelineContext.Provider
      value={{
        yamlName,
        yamlContent,
        pipelineNames,
        yamlIsValid,
        yamlError,
        status,
        jobDefinitionDraft,
        jobDefinitionName,
        jobDefinitionContent,
        setYamlName,
        setYamlContent,
        setPipelineNames,
        setYamlIsValid,
        setYamlError,
        setStatus,
        setJobDefinitionDraft,
        setJobDefinitionName,
        setJobDefinitionContent,
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
