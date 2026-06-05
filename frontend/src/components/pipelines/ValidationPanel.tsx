"use client";

import { useState } from "react";
import dynamic from "next/dynamic";

import { validateYamlContent } from "@/lib/api";
import type { ValidationReport } from "@/types";

// React Flow measures the DOM, so it must only render on the client.
const PipelineSchematic = dynamic(() => import("./PipelineSchematic"), {
  ssr: false,
  loading: () => <p className="text-xs text-slate-500">Loading diagram…</p>,
});

interface Props {
  yamlContent: string;
  onPipelinesChange: (pipelines: string[]) => void;
  onStatus: (message: string) => void;
}

export default function ValidationPanel({ yamlContent, onPipelinesChange, onStatus }: Props) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [validateImports, setValidateImports] = useState(false);
  const [selectedPipeline, setSelectedPipeline] = useState<string>("");

  async function validate() {
    const nextReport = await validateYamlContent(yamlContent, validateImports);
    setReport(nextReport);
    onPipelinesChange(nextReport.pipelines.map((pipeline) => pipeline.name));
    onStatus(nextReport.is_valid ? "YAML is valid" : "YAML has validation errors");
    setSelectedPipeline(nextReport.pipelines[0]?.name ?? "");
  }

  const pipelines = report?.pipelines ?? [];
  const activePipeline =
    pipelines.find((pipeline) => pipeline.name === selectedPipeline) ?? pipelines[0] ?? null;

  return (
    <section className="border-b border-slate-200 bg-white p-4">
      <div className="grid gap-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">Validation</h2>
            <p className="mt-1 text-xs text-slate-500">Inspect structure and optional package imports.</p>
          </div>
          <button className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white" onClick={validate}>
            Validate
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
          <input
            type="checkbox"
            checked={validateImports}
            onChange={(event) => setValidateImports(event.target.checked)}
          />
          Check imports and methods
        </label>
        {report ? (
          <div className="grid gap-2">
            <div className={`text-sm font-semibold ${report.is_valid ? "text-emerald-700" : "text-red-700"}`}>
              {report.is_valid ? "Valid" : "Invalid"}
            </div>
            {report.issues.length === 0 ? (
              <p className="text-xs text-slate-500">No issues found.</p>
            ) : (
              report.issues.map((issue, index) => (
                <div
                  key={`${issue.message}-${index}`}
                  className={`border-l-4 bg-slate-50 p-3 text-sm ${
                    issue.level === "error" ? "border-red-500" : "border-amber-500"
                  }`}
                >
                  <div className="font-semibold capitalize">{issue.level}</div>
                  <div className="text-slate-700">{issue.message}</div>
                  {[issue.pipeline, issue.section, issue.item].filter(Boolean).length > 0 ? (
                    <div className="mt-1 text-xs text-slate-500">
                      {[issue.pipeline, issue.section, issue.item].filter(Boolean).join(" / ")}
                    </div>
                  ) : null}
                </div>
              ))
            )}
            {activePipeline ? (
              <div className="grid gap-2 border-t border-slate-200 pt-3">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold text-slate-950">Schematic</h3>
                  {pipelines.length > 1 ? (
                    <select
                      className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
                      value={activePipeline.name}
                      onChange={(event) => setSelectedPipeline(event.target.value)}
                    >
                      {pipelines.map((pipeline) => (
                        <option key={pipeline.name} value={pipeline.name}>
                          {pipeline.name}
                        </option>
                      ))}
                    </select>
                  ) : null}
                </div>
                <PipelineSchematic pipeline={activePipeline} />
              </div>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No validation run yet.</p>
        )}
      </div>
    </section>
  );
}

