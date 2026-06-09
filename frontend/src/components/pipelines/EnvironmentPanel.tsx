"use client";

import { useCallback, useMemo, useState } from "react";

import { installPackage, listPackages, uninstallPackage } from "@/lib/api";
import type { PackageInfo, PackageOpResult, PackageSourceType } from "@/types";

const SOURCE_TYPES: { value: PackageSourceType; label: string; placeholder: string }[] = [
  { value: "pypi", label: "PyPI", placeholder: "labUtils==1.2.0" },
  { value: "git", label: "Git", placeholder: "labUtils @ git+https://github.com/rpazuki/lab_utils.git#subdirectory=src" },
  { value: "editable", label: "Editable path", placeholder: "/Users/me/Research/lab_utils/src" },
  { value: "requirements", label: "requirements.txt", placeholder: "/path/to/requirements.txt" },
];

export default function EnvironmentPanel() {
  const [installed, setInstalled] = useState<PackageInfo[]>([]);
  const [history, setHistory] = useState<PackageOpResult[]>([]);
  const [spec, setSpec] = useState("");
  const [sourceType, setSourceType] = useState<PackageSourceType>("pypi");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const sortedInstalled = useMemo(
    () => [...installed].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })),
    [installed],
  );

  const refresh = useCallback(async () => {
    const data = await listPackages();
    setInstalled(data.installed);
    setHistory(data.history);
    setLoaded(true);
  }, []);

  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const onConnect = () => run(refresh);

  const onInstall = () =>
    run(async () => {
      const result = await installPackage(spec, sourceType);
      if (!result.ok) {
        setError(`pip exited ${result.exit_code}: ${result.stderr.trim() || result.stdout.trim()}`);
      } else {
        setSpec("");
      }
      await refresh();
    });

  const onUninstall = (name: string) =>
    run(async () => {
      await uninstallPackage(name);
      await refresh();
    });

  const placeholder = SOURCE_TYPES.find((entry) => entry.value === sourceType)?.placeholder ?? "";

  return (
    <div className="grid gap-4">
      <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Environment access</h2>
        <p className="text-xs text-slate-500">
          Installing packages runs <code>pip</code> in the backend interpreter. This page is
          available to signed-in admins only, and installs are refused while jobs are running.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onConnect}
            disabled={busy}
            className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            Load packages
          </button>
        </div>
        {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      </section>

      {loaded ? (
        <>
          <section className="grid gap-3 rounded-md border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Install a package</h2>
            <div className="flex flex-wrap gap-2">
              <select
                aria-label="Source type"
                value={sourceType}
                onChange={(event) => setSourceType(event.target.value as PackageSourceType)}
                className="rounded-md border border-slate-300 px-2 py-2 text-sm"
              >
                {SOURCE_TYPES.map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ))}
              </select>
              <input
                aria-label="Package spec"
                value={spec}
                onChange={(event) => setSpec(event.target.value)}
                placeholder={placeholder}
                className="flex-1 rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
              />
              <button
                type="button"
                onClick={onInstall}
                disabled={busy || !spec}
                className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                Install
              </button>
            </div>
            <p className="text-xs text-amber-700">
              New packages are visible to job runs immediately. Restart the backend before
              validating pipelines against newly installed packages.
            </p>
          </section>

          <section className="grid gap-2 rounded-md border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Installed ({installed.length})</h2>
            <ul className="grid max-h-72 gap-1 overflow-y-auto">
              {sortedInstalled.map((pkg) => (
                <li
                  key={pkg.name}
                  className="flex items-center justify-between gap-2 rounded-md border border-slate-200 px-3 py-1.5 text-xs"
                >
                  <span className="font-mono text-slate-900">
                    {pkg.name}
                    <span className="text-slate-400"> {pkg.version}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => onUninstall(pkg.name)}
                    disabled={busy}
                    className="rounded-md border border-slate-300 px-2 py-0.5 font-semibold text-slate-600 disabled:opacity-50"
                  >
                    Uninstall
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="grid gap-2 rounded-md border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Install history (audit)</h2>
            {history.length === 0 ? (
              <p className="text-xs text-slate-500">No package operations recorded yet.</p>
            ) : (
              <ul className="grid gap-1">
                {history.map((entry) => (
                  <li key={entry.id} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-slate-900">
                        {entry.action} {entry.spec}
                        {entry.resolved_version ? <span className="text-slate-400"> → {entry.resolved_version}</span> : null}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 font-semibold ${entry.ok ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}>
                        {entry.ok ? "ok" : `exit ${entry.exit_code}`}
                      </span>
                    </div>
                    <div className="text-[11px] text-slate-400">
                      {entry.actor} · {entry.created_at}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
