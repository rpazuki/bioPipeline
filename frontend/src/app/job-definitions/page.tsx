"use client";

import JobDefinitionPanel from "@/components/pipelines/JobDefinitionPanel";

export default function JobDefinitionsPage() {
  return (
    <div className="grid gap-4 p-5">
      <section className="rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Job Definitions</h2>
        <p className="mt-1 text-xs text-slate-500">
          Author one declarative definition that expands into many pipeline tasks — a variable
          matrix across ordered stages, each fanned out over a mapping, pattern, or folder. Preview
          the expansion, submit it as one job, and watch the per-stage rollup.
        </p>
      </section>
      <JobDefinitionPanel />
    </div>
  );
}
