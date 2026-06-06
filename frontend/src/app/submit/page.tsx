"use client";

import Link from "next/link";

import SubmitPanel from "@/components/pipelines/SubmitPanel";
import { usePipeline } from "@/components/pipelines/PipelineContext";

export default function SubmitPage() {
  const {
    yamlName,
    pipelineNames,
    yamlIsValid,
    yamlError,
    setYamlName,
    setYamlContent,
    setPipelineNames,
    setYamlIsValid,
    setYamlError,
    setStatus,
  } = usePipeline();

  return (
    <div className="grid gap-4 p-5">
      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current YAML</div>
            <div className="mt-1 font-mono text-sm text-slate-900">{yamlName || "None selected"}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/validation" className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">
              Validate →
            </Link>
            <Link href="/storage" className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">
              Storage
            </Link>
          </div>
        </div>
        {!yamlIsValid && yamlError ? <p className="text-xs text-amber-700">{yamlError}</p> : null}
        {pipelineNames.length === 0 ? (
          <p className="text-xs text-slate-500">
            No pipelines loaded yet. Select a YAML from the tree below or open Validation to create one.
          </p>
        ) : null}
      </section>
      <SubmitPanel
        yamlName={yamlName}
        pipelineNames={pipelineNames}
        yamlIsValid={yamlIsValid}
        yamlError={yamlError}
        onYamlSelect={({ name, content, pipelines, isValid, error }) => {
          setYamlName(name);
          setYamlContent(content);
          setPipelineNames(pipelines);
          setYamlIsValid(isValid);
          setYamlError(error);
        }}
        onStatus={setStatus}
      />
    </div>
  );
}
