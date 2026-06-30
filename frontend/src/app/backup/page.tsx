"use client";

import BackupPanel from "@/components/pipelines/BackupPanel";

export default function BackupPage() {
  return (
    <div className="grid gap-4 p-5">
      <section className="rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Backup</h2>
        <p className="mt-1 text-xs text-slate-500">
          Export this project&apos;s pipelines, job definitions, and published jobs (plus the type
          library and the extra installed packages) as a single zip, or import such a zip from
          another server. This page is admin-only.
        </p>
      </section>
      <BackupPanel />
    </div>
  );
}
