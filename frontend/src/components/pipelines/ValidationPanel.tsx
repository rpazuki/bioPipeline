"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";

import { validateYamlContent } from "@/lib/api";
import {
  emitDraftsToYaml,
  parseYamlToDrafts,
  type PipelineDraft,
} from "@/lib/pipelineDraft";
import type { ValidationReport } from "@/types";

// React Flow measures the DOM, so it must only render on the client.
const PipelineBuilder = dynamic(() => import("./PipelineBuilder"), {
  ssr: false,
  loading: () => <p className="text-xs text-slate-500">Loading builder…</p>,
});

interface Props {
  yamlContent: string;
  onYamlContentChange: (content: string) => void;
  onPipelinesChange: (pipelines: string[]) => void;
  onStatus: (message: string) => void;
}

export default function ValidationPanel({
  yamlContent,
  onYamlContentChange,
  onPipelinesChange,
  onStatus,
}: Props) {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [validateImports, setValidateImports] = useState(false);
  const [drafts, setDrafts] = useState<PipelineDraft[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [parseError, setParseError] = useState<string | null>(null);
  // The text we last generated from the graph; lets the text→graph effect skip
  // re-parsing our own output (and so preserve comments until a canvas edit).
  const lastEmitted = useRef<string | null>(null);

  // Text → graph (debounced). Invalid YAML keeps the last good drafts.
  useEffect(() => {
    if (yamlContent === lastEmitted.current) return;
    if (yamlContent.trim() === "") {
      setParseError(null);
      setDrafts([]);
      return;
    }
    const timer = setTimeout(() => {
      const { drafts: parsed, error } = parseYamlToDrafts(yamlContent);
      if (error) {
        setParseError(error);
        return;
      }
      setParseError(null);
      setDrafts(parsed);
      setActiveIndex((index) => Math.min(index, Math.max(parsed.length - 1, 0)));
      onPipelinesChange(parsed.map((draft) => draft.name));
    }, 400);
    return () => clearTimeout(timer);
  }, [yamlContent, onPipelinesChange]);

  // Graph → text. Synchronous so the builder receives the updated draft at once.
  function applyDraft(next: PipelineDraft) {
    const nextDrafts = drafts.map((draft, index) => (index === activeIndex ? next : draft));
    setDrafts(nextDrafts);
    const text = emitDraftsToYaml(nextDrafts);
    lastEmitted.current = text;
    onYamlContentChange(text);
    onPipelinesChange(nextDrafts.map((draft) => draft.name));
  }

  async function validate() {
    const nextReport = await validateYamlContent(yamlContent, validateImports);
    setReport(nextReport);
    onStatus(nextReport.is_valid ? "YAML is valid" : "YAML has validation errors");
  }

  const activeDraft = drafts[Math.min(activeIndex, drafts.length - 1)] ?? null;

  return (
    <section className="border-b border-slate-200 bg-white p-4">
      <div className="grid gap-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">Validation &amp; Builder</h2>
            <p className="mt-1 text-xs text-slate-500">
              Edit the graph or the YAML — they stay in sync. Validate for full structure checks.
            </p>
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
        ) : null}

        <div className="grid gap-2 border-t border-slate-200 pt-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-slate-950">Builder</h3>
            {drafts.length > 1 ? (
              <select
                className="h-9 rounded-md border border-slate-300 px-3 text-sm text-slate-950"
                value={activeDraft?.name ?? ""}
                onChange={(event) =>
                  setActiveIndex(drafts.findIndex((draft) => draft.name === event.target.value))
                }
              >
                {drafts.map((draft) => (
                  <option key={draft.name} value={draft.name}>
                    {draft.name}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          {parseError ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
              YAML not parsed (showing last valid graph): {parseError}
            </div>
          ) : null}
          {activeDraft ? (
            <PipelineBuilder draft={activeDraft} onChange={applyDraft} />
          ) : (
            <p className="text-xs text-slate-500">Load or type a pipeline YAML to start building.</p>
          )}
        </div>
      </div>
    </section>
  );
}
