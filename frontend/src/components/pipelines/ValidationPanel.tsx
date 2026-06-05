"use client";

import { useState } from "react";

import { validateYamlContent } from "@/lib/api";
import type { ValidationReport } from "@/types";

interface Props {
  yamlContent: string;
  onPipelinesChange: (pipelines: string[]) => void;
  onStatus: (message: string) => void;
}

export default function ValidationPanel({ yamlContent, onPipelinesChange, onStatus }: Props) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [validateImports, setValidateImports] = useState(false);

  async function validate() {
    const nextReport = await validateYamlContent(yamlContent, validateImports);
    setReport(nextReport);
    onPipelinesChange(nextReport.pipelines.map((pipeline) => pipeline.name));
    onStatus(nextReport.is_valid ? "YAML is valid" : "YAML has validation errors");
  }

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
          </div>
        ) : (
          <p className="text-xs text-slate-500">No validation run yet.</p>
        )}
      </div>
    </section>
  );
}

