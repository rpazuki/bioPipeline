"use client";

import { useCallback, useState } from "react";

import { backupExportUrl, importBackup } from "@/lib/api";
import type { BackupCategoryResult, BackupImportReport } from "@/types";

function CategorySummary({ title, result }: { title: string; result: BackupCategoryResult }) {
  const { created, overwritten, skipped, errors } = result;
  return (
    <div className="rounded-md border border-slate-200 px-3 py-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold text-slate-900">{title}</span>
        <span className="text-slate-500">
          {created.length} created · {overwritten.length} overwritten · {skipped.length} skipped
          {errors.length ? ` · ${errors.length} error${errors.length === 1 ? "" : "s"}` : ""}
        </span>
      </div>
      {errors.length ? (
        <ul className="mt-1 grid gap-0.5">
          {errors.map((entry) => (
            <li key={entry.name} className="text-rose-700">
              <span className="font-mono">{entry.name}</span>: {entry.error}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default function BackupPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [installPackages, setInstallPackages] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<BackupImportReport | null>(null);

  const onImport = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await importBackup(file, { overwrite, installPackages }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [file, overwrite, installPackages]);

  const pkg = report?.packages;

  return (
    <div className="grid gap-4">
      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Export backup</h2>
        <p className="text-xs text-slate-500">
          Download a single zip containing all pipelines, job definitions, and published jobs,
          the project type library, and a <code>requirements.txt</code> of the extra packages
          installed through the Environment page. Runs, queues, logs, and users are not included.
        </p>
        <div>
          <a
            href={backupExportUrl()}
            className="inline-block rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white hover:bg-cyan-800"
          >
            Download backup zip
          </a>
        </div>
      </section>

      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Import backup</h2>
        <p className="text-xs text-slate-500">
          Upload a backup zip exported from another server. Existing items are skipped unless
          you choose to overwrite them.
        </p>
        <span className="flex flex-wrap items-center gap-2">
          <label className="cursor-pointer rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">
            Choose File
            <input
              type="file"
              accept=".zip,application/zip"
              aria-label="Backup zip file"
              className="sr-only"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setReport(null);
                setError(null);
              }}
            />
          </label>
          <span className={file ? "text-xs font-normal text-emerald-700" : "text-xs text-slate-500"}>
            {file ? file.name : "No file chosen"}
          </span>
        </span>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(event) => setOverwrite(event.target.checked)}
          />
          Overwrite existing items (otherwise they are skipped)
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            checked={installPackages}
            onChange={(event) => setInstallPackages(event.target.checked)}
          />
          Install packages from the bundled <code>requirements.txt</code>
        </label>
        <div>
          <button
            type="button"
            onClick={onImport}
            disabled={busy || !file}
            className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Importing…" : "Import backup"}
          </button>
        </div>
        <p className="text-xs text-amber-700">
          Installing packages runs <code>pip</code> in the backend interpreter and is refused
          while jobs are running. Restart the backend before validating pipelines against newly
          installed packages.
        </p>
        {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      </section>

      {report ? (
        <section className="grid gap-2 rounded-md border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-900">Import results</h2>
          <CategorySummary title="Pipelines" result={report.pipelines} />
          <CategorySummary title="Job definitions" result={report.job_definitions} />
          <CategorySummary title="Published jobs" result={report.published_jobs} />
          <CategorySummary title="Type library" result={report.type_library} />
          <div className="rounded-md border border-slate-200 px-3 py-2 text-xs">
            <span className="font-semibold text-slate-900">Packages: </span>
            {pkg && pkg.attempted ? (
              <span className={pkg.ok ? "text-emerald-700" : "text-rose-700"}>
                {pkg.ok
                  ? "installed"
                  : `failed${pkg.exit_code != null ? ` (exit ${pkg.exit_code})` : ""}`}
              </span>
            ) : (
              <span className="text-slate-500">{pkg?.detail || "not installed"}</span>
            )}
            {pkg && pkg.attempted && pkg.detail ? (
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-[11px] text-slate-600">
                {pkg.detail}
              </pre>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}
