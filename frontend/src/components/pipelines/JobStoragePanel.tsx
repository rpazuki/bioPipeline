"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { usePipeline } from "@/components/pipelines/PipelineContext";
import {
  archiveDefinition,
  deleteSavedDefinition,
  getJobDefinitionTemplate,
  getSavedDefinition,
  listArchivedDefinitions,
  listSavedDefinitions,
  restoreDefinition,
  saveDefinition,
} from "@/lib/api";
import type { DefinitionSummary } from "@/types";

export default function JobStoragePanel() {
  const router = useRouter();
  const { setJobDefinitionDraft, setStatus } = usePipeline();
  const [saved, setSaved] = useState<DefinitionSummary[]>([]);
  const [archived, setArchived] = useState<DefinitionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [activeList, archivedList] = await Promise.all([listSavedDefinitions(), listArchivedDefinitions()]);
    setSaved(activeList);
    setArchived(archivedList);
  }, []);

  useEffect(() => {
    refresh().catch((cause: Error) => setError(cause.message));
  }, [refresh]);

  const run = useCallback(
    async (action: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      try {
        await action();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const onNewJob = () =>
    run(async () => {
      const template = await getJobDefinitionTemplate("empty");
      // name: "" signals to the editor that this is a new, unsaved definition
      setJobDefinitionDraft({ name: "", content: template.content });
      setStatus("New job definition created");
      router.push("/job-definitions");
    });

  const onOpen = (name: string) =>
    run(async () => {
      const doc = await getSavedDefinition(name);
      setJobDefinitionDraft({ name: doc.name, content: doc.content });
      setStatus(`Opened ${name} in the editor`);
      router.push("/job-definitions");
    });

  const onDuplicate = (name: string) =>
    run(async () => {
      const doc = await getSavedDefinition(name);
      const parts = name.split("/");
      const fileName = parts[parts.length - 1];
      const folder = parts.slice(0, -1).join("/");
      const defaultName = folder ? `${folder}/copy_of_${fileName}` : `copy_of_${fileName}`;
      const newName = window.prompt("Duplicate as:", defaultName);
      if (!newName) return;
      await saveDefinition(newName.trim(), doc.content, false);
      await refresh();
      setStatus(`Duplicated ${name} as ${newName.trim()}`);
    });

  const onArchive = (name: string) =>
    run(async () => {
      await archiveDefinition(name);
      await refresh();
    });

  const onRestore = (name: string) =>
    run(async () => {
      await restoreDefinition(name);
      await refresh();
    });

  const onDelete = (name: string, isArchived: boolean) =>
    run(async () => {
      if (!window.confirm(`Delete definition ${name}? This cannot be undone.`)) {
        return;
      }
      await deleteSavedDefinition(name, isArchived);
      await refresh();
    });

  return (
    <div className="grid gap-4">
      <section className="grid gap-2 rounded-md border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Saved Job Definitions ({saved.length})</h2>
          <span className="flex gap-2">
            <button
              className="rounded-md bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
              onClick={onNewJob}
              disabled={busy}
            >
              New Job
            </button>
            <button
              className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => run(refresh)}
              disabled={busy}
            >
              Refresh
            </button>
          </span>
        </div>
        {error ? <p className="text-xs text-rose-700">{error}</p> : null}
        {saved.length === 0 ? (
          <p className="text-xs text-slate-500">No saved definitions yet. Author one on the Job Definitions page and Save it here.</p>
        ) : (
          <ul className="grid gap-1.5">
            {saved.map((item) => (
              <li
                key={item.name}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 px-3 py-2"
              >
                <span className="min-w-0">
                  <span className="font-mono text-xs text-slate-900">{item.name}</span>
                  {item.job ? <span className="ml-2 text-xs text-slate-500">job: {item.job}</span> : null}
                  {!item.is_valid ? (
                    <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">invalid</span>
                  ) : null}
                </span>
                <span className="flex gap-1.5">
                  <button className="rounded-md bg-cyan-700 px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-50" onClick={() => onOpen(item.name)} disabled={busy}>
                    Open
                  </button>
                  <button className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-semibold disabled:opacity-50" onClick={() => onDuplicate(item.name)} disabled={busy}>
                    Duplicate
                  </button>
                  <button className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-semibold disabled:opacity-50" onClick={() => onArchive(item.name)} disabled={busy}>
                    Archive
                  </button>
                  <button className="rounded-md border border-red-200 px-2.5 py-1 text-xs font-semibold text-red-700 disabled:opacity-50" onClick={() => onDelete(item.name, false)} disabled={busy}>
                    Delete
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="grid gap-2 rounded-md border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Archived ({archived.length})</h2>
        {archived.length === 0 ? (
          <p className="text-xs text-slate-500">No archived definitions.</p>
        ) : (
          <ul className="grid gap-1.5">
            {archived.map((item) => (
              <li
                key={item.name}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2"
              >
                <span className="font-mono text-xs text-slate-600">
                  {item.name}
                  {item.job ? <span className="ml-2 text-slate-400">job: {item.job}</span> : null}
                </span>
                <span className="flex gap-1.5">
                  <button className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-semibold disabled:opacity-50" onClick={() => onRestore(item.name)} disabled={busy}>
                    Restore
                  </button>
                  <button className="rounded-md border border-red-200 px-2.5 py-1 text-xs font-semibold text-red-700 disabled:opacity-50" onClick={() => onDelete(item.name, true)} disabled={busy}>
                    Delete
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
