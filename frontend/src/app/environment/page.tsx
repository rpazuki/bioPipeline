"use client";

import EnvironmentPanel from "@/components/pipelines/EnvironmentPanel";
import TypeLibraryPanel from "@/components/pipelines/TypeLibraryPanel";

export default function EnvironmentPage() {
  return (
    <div className="grid gap-4 p-5">
      <section className="rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Environment</h2>
        <p className="mt-1 text-xs text-slate-500">
          Install the science and pipeline packages your YAMLs import (e.g. <code>labUtils</code>)
          into the backend&apos;s Python environment, and manage the reusable type library. This page
          is admin-only, and installs are refused while jobs are running.
        </p>
      </section>
      <TypeLibraryPanel />
      <EnvironmentPanel />
    </div>
  );
}
