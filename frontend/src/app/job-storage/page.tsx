"use client";

import JobStoragePanel from "@/components/pipelines/JobStoragePanel";

export default function JobStoragePage() {
  return (
    <div className="grid gap-4 p-5">
      <section className="rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Job Storage</h2>
        <p className="mt-1 text-xs text-slate-500">
          Saved, reusable Job Definitions. Open one to load it into the editor, archive ones you no
          longer need (recoverable), or delete them permanently.
        </p>
      </section>
      <JobStoragePanel />
    </div>
  );
}
